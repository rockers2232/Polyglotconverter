import ast
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ==========================================
#  1. UNIVERSAL IR
# ==========================================
class UniversalIR:
    def __init__(self):
        self.instructions = []

    def add(self, instr):
        self.instructions.append(instr)

# ==========================================
#  2. PYTHON PARSER
# ==========================================
class PythonParser:
    def parse(self, code):
        ir = UniversalIR()
        try:
            tree = ast.parse(code)
            self._visit_block(tree.body, ir.instructions)
        except Exception as e:
            ir.instructions.append({'action': 'COMMENT', 'text': f"Error: {e}"})
        return ir

    def _visit_block(self, nodes, block):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom)):
                continue

            if isinstance(node, ast.If) and self._is_main_check(node):
                self._visit_block(node.body, block)
                continue

            # ASSIGNMENT
            if isinstance(node, ast.Assign):
                target = node.targets[0].id
                val, vtype = self._eval_val(node.value)
                block.append({'action': 'ASSIGN', 'name': target, 'value': val, 'type': vtype})

            # PRINT
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                if getattr(node.value.func, 'id', '') == 'print':
                    args = []
                    for arg in node.value.args:
                        val, _ = self._eval_val(arg)
                        is_str = '"' in val
                        args.append({'val': val.replace('"', ''), 'type': 'string' if is_str else 'var'})
                    block.append({'action': 'PRINT', 'parts': args})

            # CONTROL FLOW
            elif isinstance(node, ast.If):
                cond = self._eval_cond(node.test)
                if_body = []
                self._visit_block(node.body, if_body)
                else_body = []
                if node.orelse:
                    self._visit_block(node.orelse, else_body)
                block.append({'action': 'IF', 'condition': cond, 'body': if_body, 'else_body': else_body})

            elif isinstance(node, ast.While):
                cond = self._eval_cond(node.test)
                loop_body = []
                self._visit_block(node.body, loop_body)
                block.append({'action': 'WHILE', 'condition': cond, 'body': loop_body})

            elif isinstance(node, ast.For):
                target = node.target.id
                limit = "10"
                if isinstance(node.iter, ast.Call) and node.iter.func.id == 'range':
                    arg = node.iter.args[0]
                    limit = self._eval_val(arg)[0]
                loop_body = []
                self._visit_block(node.body, loop_body)
                block.append({'action': 'FOR', 'var': target, 'limit': limit, 'body': loop_body})

    def _eval_val(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str): return f'"{node.value}"', 'String'
            if isinstance(node.value, float): return str(node.value), 'double'
            return str(node.value), 'int'
        if isinstance(node, ast.Name): return node.id, 'var'
        if isinstance(node, ast.BinOp):
            left, _ = self._eval_val(node.left)
            right, _ = self._eval_val(node.right)
            op_map = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/'}
            op = op_map.get(type(node.op), '+')
            return f"{left} {op} {right}", 'auto'
        return "0", 'int'

    def _eval_cond(self, node):
        if isinstance(node, ast.Compare):
            left, _ = self._eval_val(node.left)
            right, _ = self._eval_val(node.comparators[0])
            ops = {ast.Eq: '==', ast.Gt: '>', ast.Lt: '<', ast.GtE: '>=', ast.LtE: '<='}
            op = ops.get(type(node.ops[0]), '==')
            return f"{left} {op} {right}"
        return "true"

    def _is_main_check(self, node):
        try:
            return (isinstance(node.test, ast.Compare) and 
                    node.test.left.id == '__name__' and 
                    node.test.comparators[0].value == '__main__')
        except: return False

# ==========================================
#  3. GENERATOR (With Variable Tracking)
# ==========================================
class Generator:
    def generate(self, ir, lang):
        self.out = []
        self.lang = lang
        self.declared_vars = set() # Track variables to prevent re-declaration
        
        # Headers
        if lang == 'c': self.out.append('#include <stdio.h>\n\nint main() {')
        elif lang == 'cpp': self.out.append('#include <iostream>\nusing namespace std;\n\nint main() {')
        elif lang == 'java': self.out.append('public class Main {\n    public static void main(String[] args) {')

        # Generate Body
        indent = 2 if lang == 'java' else 1
        self._gen_block(ir.instructions, indent)

        # Footers
        if lang == 'java': self.out.append('    }\n}')
        else: self.out.append('    return 0;\n}')

        return "\n".join(self.out)

    def _gen_block(self, instructions, indent_lvl):
        tab = "    " * indent_lvl
        
        for instr in instructions:
            action = instr['action']
            
            if action == 'ASSIGN':
                name = instr['name']
                val = instr['value']
                vtype = instr['type']
                
                # Logic: If variable seen before -> Assignment. Else -> Declaration.
                if name in self.declared_vars:
                    self.out.append(f"{tab}{name} = {val};")
                else:
                    self.declared_vars.add(name)
                    # Type Fixes
                    if vtype == 'auto' or vtype == 'var': vtype = 'int'
                    if self.lang == 'java' and vtype == 'String': vtype = 'String'
                    elif self.lang == 'c' and vtype == 'String': vtype = 'char*'
                    elif self.lang == 'cpp' and vtype == 'String': vtype = 'string'
                    
                    self.out.append(f"{tab}{vtype} {name} = {val};")

            elif action == 'PRINT':
                parts = instr['parts']
                if self.lang == 'cpp':
                    stream = " << ".join([f'"{p["val"]}"' if p['type']=='string' else ("\" \" << " + p['val']) if i>0 else p['val'] for i,p in enumerate(parts)])
                    self.out.append(f"{tab}cout << {stream} << endl;")
                elif self.lang == 'java':
                    stream = " + ".join([f'"{p["val"]}"' if p['type']=='string' else ("\" \" + " + p['val']) if i>0 else p['val'] for i,p in enumerate(parts)])
                    self.out.append(f"{tab}System.out.println({stream});")
                elif self.lang == 'c':
                    fmt = " ".join(["%s" if p['type']=='string' else "%d" for p in parts]) 
                    vals = ", ".join([f'"{p["val"]}"' if p['type']=='string' else p['val'] for p in parts])
                    self.out.append(f'{tab}printf("{fmt}\\n", {vals});')

            elif action == 'FOR':
                var = instr['var']
                limit = instr['limit']
                self.out.append(f"{tab}for(int {var}=0; {var}<{limit}; {var}++) {{")
                self.declared_vars.add(var) # Register loop variable
                self._gen_block(instr['body'], indent_lvl + 1)
                self.out.append(f"{tab}}}")
            
            elif action == 'WHILE':
                self.out.append(f"{tab}while ({instr['condition']}) {{")
                self._gen_block(instr['body'], indent_lvl + 1)
                self.out.append(f"{tab}}}")
            
            elif action == 'IF':
                self.out.append(f"{tab}if ({instr['condition']}) {{")
                self._gen_block(instr['body'], indent_lvl + 1)
                if instr['else_body']:
                    self.out.append(f"{tab}}} else {{")
                    self._gen_block(instr['else_body'], indent_lvl + 1)
                self.out.append(f"{tab}}}")

# ==========================================
#  4. SERVER
# ==========================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/convert', methods=['POST'])
def convert():
    data = request.json
    parser = PythonParser()
    ir = parser.parse(data.get('code'))
    generator = Generator()
    return jsonify({'result': generator.generate(ir, data.get('toLang'))})

if __name__ == '__main__':
    app.run(debug=True, port=5000)