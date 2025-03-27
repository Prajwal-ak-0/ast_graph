import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def find_ast_files(directory):
    """Finds all .json files recursively in a directory."""
    ast_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".json"): # Assuming ASTs are saved as .json
                 # Use pathlib for consistent path separators
                file_path = Path(root) / file
                ast_files.append(str(file_path))
    logging.info(f"Found {len(ast_files)} AST files in '{directory}'.")
    return ast_files

def get_node_name(node):
    """Safely gets the name from various identifier/name nodes."""
    if not node:
        return None
    node_type = node.get('type')
    if node_type in ['Identifier', 'PrivateName']:
        return node.get('name')
    elif node_type == 'ClassDeclaration':
        return node.get('id', {}).get('name')
    elif node_type == 'MethodDefinition':
        return get_node_name(node.get('key'))
    elif node_type == 'TSInterfaceDeclaration':
         return node.get('id', {}).get('name')
    elif node_type == 'FunctionDeclaration':
         return node.get('id', {}).get('name')
    elif node_type == 'VariableDeclarator':
         return node.get('id', {}).get('name')
    elif node_type == 'MemberExpression':
         # Combine object and property for a qualified name attempt
        obj_name = get_node_name(node.get('object'))
        prop_name = get_node_name(node.get('property'))
        return f"{obj_name}.{prop_name}" if obj_name and prop_name else prop_name
    elif node_type == 'Literal':
        return str(node.get('value')) # Represent literals as strings
    # Add more types as needed
    return None

def format_arguments(args_nodes):
    """Formats call expression arguments into a readable string."""
    if not args_nodes:
        return "()"
    arg_strings = []
    for arg in args_nodes:
        arg_name = get_node_name(arg)
        if arg_name:
            arg_strings.append(arg_name)
        elif arg.get('type') == 'Literal':
             arg_strings.append(repr(arg.get('value'))) # Use repr for literals
        elif arg.get('type') == 'ObjectExpression':
             arg_strings.append('{...}') # Simplified object literal
        elif arg.get('type') == 'ArrayExpression':
             arg_strings.append('[...]') # Simplified array literal
        else:
            arg_strings.append(arg.get('type', 'unknown')) # Fallback to type
    return f"({', '.join(arg_strings)})"

def extract_calls(node, current_calls):
    """Recursively traverses AST nodes to find CallExpressions."""
    if not isinstance(node, dict):
        return

    node_type = node.get('type')

    if node_type == 'CallExpression':
        callee = node.get('callee')
        is_await = False # Check parent for AwaitExpression

        # Basic callee parsing
        base_expression = None
        called_method_name = None

        if callee:
             callee_type = callee.get('type')
             if callee_type == 'MemberExpression':
                 base_node = callee.get('object')
                 method_node = callee.get('property')
                 # Try to get a string representation of the base
                 if base_node:
                     if base_node.get('type') == 'ThisExpression':
                         base_expression = 'this'
                     else:
                         base_expression = get_node_name(base_node) or 'unknown_base'
                 called_method_name = get_node_name(method_node)
             elif callee_type == 'Identifier':
                 called_method_name = get_node_name(callee)
                 base_expression = None # Global function or similar
             # Handle super() calls
             elif callee_type == 'Super':
                 called_method_name = 'super'
                 base_expression = None


        if called_method_name: # Only record if we could identify a method name
            call_info = {
                'base_expression': base_expression,
                'called_method_name': called_method_name,
                'arguments_str': format_arguments(node.get('arguments')),
                'is_await': is_await # Note: Await check needs parent context, simplified here
            }
            # Simplistic await check (might miss some cases)
            if node.get('_parent_type') == 'AwaitExpression': # Requires pre-processing or passing parent
                 call_info['is_await'] = True

            current_calls.append(call_info)

    # Recurse through children - assigning _parent_type helps await check
    for key, value in node.items():
        if key == 'range' or key == 'loc' or key == 'decorators': # Skip metadata and decorators here
            continue
        if isinstance(value, dict):
             value['_parent_type'] = node_type # Pass parent type down
             extract_calls(value, current_calls)
             del value['_parent_type'] # Clean up temporary key
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                     item['_parent_type'] = node_type
                     extract_calls(item, current_calls)
                     del item['_parent_type']

def extract_decorators(decorator_nodes):
    """Extracts information from decorator nodes."""
    decorators = []
    if not decorator_nodes:
        return decorators
    for dec in decorator_nodes:
        expression = dec.get('expression')
        if not expression: continue
        decorator_name = None
        arguments_str = "()" # Default for decorator without call ()

        if expression.get('type') == 'CallExpression':
            decorator_name = get_node_name(expression.get('callee'))
            arguments_str = format_arguments(expression.get('arguments'))
        elif expression.get('type') == 'Identifier':
            decorator_name = get_node_name(expression)
            # No arguments if it's just @DecoratorName

        if decorator_name:
             decorators.append({
                 'name': decorator_name,
                 'arguments_str': arguments_str
             })
    return decorators

def get_type_annotation_str(node):
    """Extracts a string representation of a type annotation."""
    if not node: return 'any'
    type_ann = node.get('typeAnnotation')
    if not type_ann:
        # Handle cases like constructor param properties where type is one level up
        type_ann = node.get('parameter', {}).get('typeAnnotation', {}).get('typeAnnotation')
        if not type_ann:
             # Or VariableDeclarator init type
             type_ann = node.get('id', {}).get('typeAnnotation', {}).get('typeAnnotation')
             if not type_ann:
                 return 'any' # Give up

    type_kind = type_ann.get('type')

    if type_kind == 'TSTypeReference':
        name = get_node_name(type_ann.get('typeName'))
        args = type_ann.get('typeArguments', {}).get('params', [])
        if args:
            arg_strs = [get_type_annotation_str(a) for a in args]
            # Hack: TS parser wraps type args in another typeAnnotation sometimes
            arg_strs = [s.replace(": any","") if isinstance(s, str) and s.endswith(': any') else s for s in arg_strs] # Clean up common wrapper issue
            return f"{name}<{', '.join(arg_strs)}>"
        return name or 'unknown'
    elif type_kind in ['TSStringKeyword', 'TSNumberKeyword', 'TSBooleanKeyword', 'TSVoidKeyword', 'TSAnyKeyword', 'TSNullKeyword', 'TSUndefinedKeyword', 'TSNeverKeyword', 'TSUnknownKeyword', 'TSSymbolKeyword', 'TSObjectKeyword']:
        return type_kind.replace('Keyword', '').replace('TS', '').lower()
    elif type_kind == 'TSUnionType':
        return ' | '.join(get_type_annotation_str(t) for t in type_ann.get('types', []))
    elif type_kind == 'TSIntersectionType':
        return ' & '.join(get_type_annotation_str(t) for t in type_ann.get('types', []))
    elif type_kind == 'TSTypeLiteral':
        return '{...}' # Simplified
    elif type_kind == 'TSArrayType':
        elem_type = get_type_annotation_str(type_ann.get('elementType'))
        return f"{elem_type}[]"
    elif type_kind == 'TSTupleType':
        elem_types = [get_type_annotation_str(t) for t in type_ann.get('elementTypes', [])]
        return f"[{', '.join(elem_types)}]"
    # Add more TS types as needed
    return 'any' # Fallback


def extract_parameters(param_nodes):
    """Extracts parameter names and types."""
    params = []
    deps = [] # For constructor injected dependencies
    if not param_nodes:
        return params, deps

    for p in param_nodes:
        param_info = {'name': 'unknown', 'type': 'any'}
        is_dependency = False
        if p.get('type') == 'Identifier':
            param_info['name'] = get_node_name(p)
            param_info['type'] = get_type_annotation_str(p.get('typeAnnotation'))
        elif p.get('type') == 'TSParameterProperty': # Constructor injection
            param_node = p.get('parameter')
            if param_node and param_node.get('type') == 'Identifier':
                param_info['name'] = get_node_name(param_node)
                param_info['type'] = get_type_annotation_str(param_node.get('typeAnnotation'))
                is_dependency = True
                dep_info = {
                    'name': param_info['name'],
                    'type': param_info['type'],
                    'accessibility': p.get('accessibility'), # public, private, protected
                    'readonly': p.get('readonly', False)
                }
                deps.append(dep_info)
        elif p.get('type') == 'AssignmentPattern': # Default value parameter
            left = p.get('left')
            if left and left.get('type') == 'Identifier':
                 param_info['name'] = get_node_name(left)
                 param_info['type'] = get_type_annotation_str(left.get('typeAnnotation'))
                 param_info['default'] = True # Mark as having a default

        # Add other parameter types like RestElement if needed

        if not is_dependency: # Only add non-injected to regular params
            params.append(param_info)

    return params, deps


def extract_features_from_ast(ast_data, file_path_str, config):
    """Extracts structured features from a single AST JSON."""
    if not ast_data or not isinstance(ast_data, dict):
        logging.warning(f"Invalid or empty AST data for {file_path_str}")
        return None

    # Use pathlib for easier manipulation
    file_path = Path(file_path_str)
    relative_path = file_path_str # Assuming input paths are already relative or absolute as desired
    try:
        # Attempt to make path relative to project root if possible
        # This might need adjustment based on where the script runs
        relative_path = str(file_path.relative_to(Path.cwd()))
    except ValueError:
        # If not relative to CWD, use the original path
        pass


    file_id = relative_path
    extracted = {
        'file_id': file_id,
        'file_path': relative_path,
        'imports': [],
        'exports': [],
        'entities': {}, # entity_id -> entity_data
        'methods': {}, # method_id -> method_data
        'calls': {}, # method_id -> [call_info]
        'dependencies': {}, # entity_id -> [dep_info]
        'decorators': {} # target_id -> [decorator_info]
    }

    source_root = config.get('source_code_root_prefix', 'src/')

    body = ast_data.get('body', [])
    if not body:
        logging.warning(f"AST body is empty for {file_path}")
        return extracted # Return structure with empty lists/dicts

    for node in body:
        node_type = node.get('type')

        # --- Imports ---
        if node_type == 'ImportDeclaration':
            source = node.get('source', {}).get('value')
            if not source: continue

            is_external = not (source.startswith('.') or source.startswith('/') or source.startswith(source_root))
            specifiers = [get_node_name(s.get('imported', s.get('local'))) for s in node.get('specifiers', [])]
             # Handle default imports correctly (local name might differ)
            default_specifier = next((s.get('local',{}).get('name') for s in node.get('specifiers', []) if s.get('type') == 'ImportDefaultSpecifier'), None)
            if default_specifier and default_specifier not in specifiers:
                 specifiers.append(f"default({default_specifier})") # Mark default import clearly

            extracted['imports'].append({
                'source': source,
                'specifiers': specifiers,
                'is_external': is_external
            })

        # --- Exports ---
        elif node_type == 'ExportNamedDeclaration':
            declaration = node.get('declaration')
            if declaration: # export const foo = ...; export class Bar {}
                 decl_type = declaration.get('type')
                 name = get_node_name(declaration)
                 kind = decl_type.replace('Declaration', '') if name else 'Unknown'
                 if name:
                    extracted['exports'].append({'name': name, 'kind': kind})
            else: # export { foo, bar };
                 specifiers = node.get('specifiers', [])
                 for spec in specifiers:
                      name = get_node_name(spec.get('exported'))
                      # Kind might be unknown here without tracing back definition
                      if name:
                           extracted['exports'].append({'name': name, 'kind': 'Unknown'})

        elif node_type == 'ExportDefaultDeclaration':
            declaration = node.get('declaration')
            name = get_node_name(declaration) or 'default' # Often anonymous
            kind = declaration.get('type', 'Unknown').replace('Declaration','') if name != 'default' else 'Unknown'
            extracted['exports'].append({'name': name, 'kind': kind})

        # --- Entities (Classes, Interfaces, Functions at top level) ---
        elif node_type in ['ClassDeclaration', 'TSInterfaceDeclaration', 'FunctionDeclaration']:
            entity_name = get_node_name(node)
            if not entity_name: continue # Skip anonymous/unidentifiable entities

            entity_id = f"{file_id}::{entity_name}"
            kind = node_type.replace('Declaration', '')
            entity_decorators = extract_decorators(node.get('decorators'))
            if entity_decorators:
                extracted['decorators'][entity_id] = entity_decorators

            entity_data = {
                'entity_id': entity_id,
                'name': entity_name,
                'kind': kind,
                'file_id': file_id,
            }
            extracted['entities'][entity_id] = entity_data

            # Class specifics
            if node_type == 'ClassDeclaration':
                super_class_node = node.get('superClass')
                if super_class_node:
                    entity_data['superClass'] = get_node_name(super_class_node)

                implements_nodes = node.get('implements', [])
                entity_data['implements'] = [get_node_name(imp.get('expression')) for imp in implements_nodes if get_node_name(imp.get('expression'))]


                # Process methods and constructor
                class_body = node.get('body', {}).get('body', [])
                for member in class_body:
                    member_type = member.get('type')
                    if member_type == 'MethodDefinition':
                        method_name = get_node_name(member)
                        if not method_name: continue

                        method_id = f"{entity_id}::{method_name}"
                        is_async = member.get('value', {}).get('async', False)
                        params, constructor_deps = extract_parameters(member.get('value', {}).get('params'))
                        return_type = get_type_annotation_str(member.get('value', {}).get('returnType'))

                        method_decorators = extract_decorators(member.get('decorators'))
                        if method_decorators:
                            extracted['decorators'][method_id] = method_decorators

                        method_data = {
                            'method_id': method_id,
                            'name': method_name,
                            'kind': member.get('kind', 'method'), # constructor, method, get, set
                            'entity_id': entity_id,
                            'is_async': is_async,
                            'parameters': params,
                            'return_type': return_type,
                        }
                        extracted['methods'][method_id] = method_data

                        # Store constructor dependencies separately
                        if method_data['kind'] == 'constructor' and constructor_deps:
                            extracted['dependencies'][entity_id] = constructor_deps

                        # Extract calls within the method
                        method_body_node = member.get('value', {}).get('body')
                        if method_body_node:
                             calls = []
                             extract_calls(method_body_node, calls)
                             if calls:
                                extracted['calls'][method_id] = calls

                    # Add PropertyDefinition if needed
            # Add Function/Interface specifics if needed

        # Handle top-level variables/constants if needed
        elif node_type == 'VariableDeclaration':
             for declaration in node.get('declarations', []):
                 if declaration.get('type') == 'VariableDeclarator':
                    var_name = get_node_name(declaration)
                    if not var_name: continue
                    # Treat top-level const/let/var as entities for simplicity
                    entity_id = f"{file_id}::{var_name}"
                    init_node = declaration.get('init')
                    kind_detail = init_node.get('type', 'Unknown') if init_node else 'Unknown' # e.g. ArrowFunctionExpression, Literal
                    entity_data = {
                         'entity_id': entity_id,
                         'name': var_name,
                         'kind': 'Variable',
                         'kind_detail': kind_detail, # More specific type if available
                         'file_id': file_id,
                         'var_kind': node.get('kind') # const, let, var
                     }
                    # Could potentially extract calls if init is a function expr
                    extracted['entities'][entity_id] = entity_data


    return extracted