from pyvis.network import Network
import networkx as nx
import logging
import json
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Basic color mapping
NODE_COLORS = {
    'File': '#CCCCCC', # Grey
    'Class': '#4CAF50', # Green
    'Interface': '#2196F3', # Blue
    'Function': '#FFC107', # Amber
    'Method': '#FF9800', # Orange
    'Variable': '#9C27B0', # Purple
    'External': '#F44336', # Red
    'Unknown': '#795548', # Brown
    # Add more kinds as needed
}
DEFAULT_NODE_COLOR = '#607D8B' # Blue Grey

EDGE_COLORS = {
    'CONTAINS': '#E0E0E0',
    'CONTAINS_FUNC': '#E0E0E0',
    'IMPORTS_INT': '#BDBDBD',
    'IMPORTS_EXT': '#F48FB1', # Pinkish Red
    'HAS_METHOD': '#C8E6C9', # Light Green
    'INJECTS': '#FFCCBC', # Light Deep Orange
    'CALLS': '#BBDEFB', # Light Blue
    'CALLS_EXT': '#FFCDD2', # Light Red
    'EXTENDS': '#D1C4E9', # Light Purple
    'IMPLEMENTS': '#C5CAE9', # Light Indigo
}
DEFAULT_EDGE_COLOR = '#9E9E9E' # Grey

def visualize_pyvis(G, output_path_str, config):
    """Visualizes the graph using Pyvis."""
    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True) # Ensure output dir exists

    logging.info(f"Generating Pyvis visualization at: {output_path}")

    pyvis_net = Network(height='90vh', width='100%', directed=True, notebook=False, heading='Codebase Graph')

    # --- Add Nodes ---
    for node_id, attrs in G.nodes(data=True):
        node_type = attrs.get('type', 'Unknown')
        color = NODE_COLORS.get(node_type, DEFAULT_NODE_COLOR)
        label = attrs.get('label', str(node_id)) # Use pre-defined label or ID
        title = attrs.get('title', node_id) # Hover text
        size = 15 # Default size
        if node_type == 'File': size = 25
        elif node_type == 'Class': size = 20
        elif node_type == 'External': size = 18

        pyvis_net.add_node(
            node_id,
            label=label,
            title=title,
            color=color,
            size=size,
            shape='dot' # Use 'box' for files? 'database' for external?
        )

    # --- Add Edges ---
    for u, v, attrs in G.edges(data=True):
        edge_type = attrs.get('type', 'Unknown')
        color = EDGE_COLORS.get(edge_type, DEFAULT_EDGE_COLOR)
        label = attrs.get('label', '') # Optional edge label
        title = edge_type # Show edge type on hover
        width = 1
        dashes = False
        if edge_type.startswith('IMPORTS'): width = 0.5
        elif edge_type == 'CALLS': width = 1.5
        elif edge_type == 'INJECTS': dashes = True; width = 1.5

        pyvis_net.add_edge(
            u, v,
            title=title,
            label=label,
            color=color,
            width=width,
            dashes=dashes,
            # arrows='to' # Default for directed graph
        )

    # --- Apply Pyvis Options ---
    pyvis_options_str = config.get('graph_config', {}).get('pyvis_options', '{}')
    try:
        pyvis_options = json.loads(pyvis_options_str)
        if pyvis_options:
            # pyvis_net.set_options(json.dumps(pyvis_options)) # Newer pyvis?
             options_str = json.dumps(pyvis_options)
             pyvis_net.set_options(options_str) # Pass options as JSON string
             logging.info("Applied custom Pyvis options.")
    except json.JSONDecodeError as e:
        logging.warning(f"Could not parse pyvis_options from config: {e}")
    except Exception as e:
         logging.warning(f"Could not apply Pyvis options: {e}")


    # --- Save Visualization ---
    try:
        pyvis_net.save_graph(str(output_path))
        logging.info(f"Graph visualization saved successfully to {output_path}")
    except Exception as e:
        logging.error(f"Failed to save Pyvis graph: {e}", exc_info=True)