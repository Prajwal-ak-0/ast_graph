import networkx as nx
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def resolve_internal_path(current_file_path_str, import_source, all_file_ids):
    """Tries to resolve a relative import path to an absolute file_id."""
    current_dir = Path(current_file_path_str).parent
    resolved_path = (current_dir / import_source).resolve()

    # Attempt common resolutions (.ts, .js, /index.ts, /index.js)
    potential_extensions = ['.ts', '.tsx', '.js', '.jsx']
    potential_files = []

    # 1. Direct file match
    for ext in potential_extensions:
        potential_files.append(resolved_path.with_suffix(ext))

    # 2. Index file match in directory
    if not resolved_path.suffix: # If import is './folder'
        for ext in potential_extensions:
            potential_files.append(resolved_path / f"index{ext}")

    # Check if any potential resolved path exists in our known files
    for p_file in potential_files:
         # Normalize path for comparison (make relative to CWD if possible)
         try:
              rel_p_file = str(p_file.relative_to(Path.cwd()))
              if rel_p_file in all_file_ids:
                   return rel_p_file
         except ValueError:
              abs_p_file = str(p_file)
              if abs_p_file in all_file_ids: # Check absolute path match if relative fails
                   return abs_p_file
              # Also check if the simple relative path (as stored in file_id) matches
              simple_rel = str(current_dir.relative_to(Path.cwd()) / import_source) + p_file.suffix
              if simple_rel in all_file_ids:
                  return simple_rel

    logging.debug(f"Could not resolve internal import '{import_source}' from '{current_file_path_str}' to a known file ID.")
    return None # Cannot resolve


def build_graph(extracted_data, config):
    """Builds a NetworkX graph from the extracted data."""
    G = nx.DiGraph()
    all_file_ids = list(extracted_data.keys()) # Get all processed file IDs

    logging.info("Building graph nodes...")
    # --- Add Nodes ---
    for file_id, data in extracted_data.items():
        # File Node
        G.add_node(file_id, type='File', path=data['file_path'], label=Path(data['file_path']).name)

        # Entity Nodes
        for entity_id, entity in data.get('entities', {}).items():
            label = entity.get('name', 'Unknown')
            title = f"Kind: {entity.get('kind')}\nFile: {file_id}"
            if 'description' in entity:
                title += f"\nDesc: {entity['description']}"
            G.add_node(entity_id, type=entity.get('kind', 'Unknown'), name=label, file_id=file_id, label=label, title=title, description=entity.get('description'))
            # File -> Entity Edge
            G.add_edge(file_id, entity_id, type='CONTAINS')

        # Method Nodes
        for method_id, method in data.get('methods', {}).items():
            entity_id = method.get('entity_id')
            method_name = method.get('name', 'unknown')
            label = f"{method_name}()"
            title = f"Method: {method_name}\nKind: {method.get('kind')}\nEntity: {entity_id or 'N/A'}\nFile: {file_id}"
            if 'summary' in method:
                title += f"\nSummary: {method['summary']}"

            G.add_node(method_id, type='Method', name=method_name, entity_id=entity_id, file_id=file_id, label=label, title=title, summary=method.get('summary'))
            # Entity -> Method Edge
            if entity_id and G.has_node(entity_id):
                G.add_edge(entity_id, method_id, type='HAS_METHOD')
            elif file_id: # Attach to file if no parent entity (e.g. top level func)
                 G.add_edge(file_id, method_id, type='CONTAINS_FUNC') # Different edge type


    logging.info("Building graph edges...")
    # --- Add Edges ---
    processed_external_imports = set() # Avoid duplicate external nodes

    for file_id, data in extracted_data.items():
        # Import Edges
        for imp in data.get('imports', []):
            source = imp['source']
            if imp['is_external']:
                if source not in processed_external_imports:
                     G.add_node(source, type='External', label=source, title=f"External Library: {source}")
                     processed_external_imports.add(source)
                G.add_edge(file_id, source, type='IMPORTS_EXT', label=', '.join(imp['specifiers']))
            else: # Internal import
                target_file_id = resolve_internal_path(data['file_path'], source, all_file_ids)
                if target_file_id and G.has_node(target_file_id):
                    G.add_edge(file_id, target_file_id, type='IMPORTS_INT', label=Path(source).name) # Show relative path on edge
                else:
                    # Could add an 'Unresolved Import' node if desired
                    logging.debug(f"Import edge skipped: Cannot resolve internal import '{source}' from '{file_id}'")


        # Dependency Injection Edges
        for entity_id, deps in data.get('dependencies', {}).items():
            if not G.has_node(entity_id): continue
            for dep in deps:
                dep_type_name = dep['type']
                # Simplistic resolution: Find entity with matching name ANYWHERE
                # This is inaccurate if names clash across files! A better approach
                # would trace imports to find the specific entity ID.
                target_entity_id = next((eid for eid, e_data in data.get('entities', {}).items() if e_data.get('name') == dep_type_name), None)
                 # If not found in current file's scope, search globally (less accurate)
                if not target_entity_id:
                     target_entity_id = next((eid for f_data in extracted_data.values() for eid, e_data in f_data.get('entities', {}).items() if e_data.get('name') == dep_type_name), None)

                if target_entity_id and G.has_node(target_entity_id):
                     G.add_edge(entity_id, target_entity_id, type='INJECTS', label=f"as {dep['name']}")
                else:
                     logging.debug(f"Injection edge skipped: Cannot resolve dependency type '{dep_type_name}' for '{entity_id}'")

        # Call Edges
        for method_id, calls in data.get('calls', {}).items():
             if not G.has_node(method_id): continue
             caller_method_data = G.nodes[method_id]
             caller_entity_id = caller_method_data.get('entity_id')

             for call in calls:
                 base = call.get('base_expression')
                 target_method_name = call.get('called_method_name')
                 target_method_id = None

                 # --- Attempt Call Resolution (Simplified) ---
                 if base == 'this' and caller_entity_id:
                     # Look for method in the same class
                     target_method_id = f"{caller_entity_id}::{target_method_name}"
                 elif base:
                     # Is 'base' an injected dependency?
                     caller_deps = data.get('dependencies', {}).get(caller_entity_id, [])
                     dep_match = next((dep for dep in caller_deps if dep.get('name') == base), None)
                     if dep_match:
                          dep_type_name = dep_match['type']
                          # Find the entity corresponding to the dependency type (global search - inaccurate)
                          dep_entity_id = next((eid for f_data in extracted_data.values() for eid, e_data in f_data.get('entities', {}).items() if e_data.get('name') == dep_type_name), None)
                          if dep_entity_id:
                               target_method_id = f"{dep_entity_id}::{target_method_name}"
                     # Else: Could it be an imported module/function call? (More complex to trace)

                 # Else (base is None): Could be a global function or function in same file scope (needs more context)


                 # --- Add Edge if Resolved ---
                 if target_method_id and G.has_node(target_method_id):
                      label = "await" if call.get('is_await') else ""
                      G.add_edge(method_id, target_method_id, type='CALLS', label=label)
                 elif base and not target_method_id: # Could be call to external lib or unresolved
                       if G.has_node(base): # If base is an external lib node
                           # Add edge from method to external lib node
                           G.add_edge(method_id, base, type='CALLS_EXT', label=target_method_name)
                       else:
                           logging.debug(f"Call edge skipped: Cannot resolve target for {base}.{target_method_name}() from '{method_id}'")
                 elif not base and target_method_name: # Global/local func call
                      logging.debug(f"Call edge skipped: Cannot resolve target for global/local func {target_method_name}() from '{method_id}'")


        # Decorator Edges (attach decorator info to node title instead of separate edges for simplicity now)
        # If separate nodes desired: Create decorator nodes and add edges
        # for target_id, decorators in data.get('decorators', {}).items():
        #     if G.has_node(target_id):
        #          for dec in decorators:
        #              # G.add_edge(target_id, dec['name'], type='DECORATED_BY', label=dec['arguments_str'])


    logging.info(f"Graph built with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
    return G