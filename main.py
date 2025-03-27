import yaml
import json
import logging
from pathlib import Path
from tqdm import tqdm

from ast_parser import find_ast_files, extract_features_from_ast
from llm_enhancer import enhance_data_with_llm
from graph_builder import build_graph
from visualizer import visualize_pyvis

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config(config_path='config.yaml'):
    """Loads YAML configuration file."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        logging.info(f"Configuration loaded from {config_path}")
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found at {config_path}")
        return None
    except yaml.YAMLError as e:
        logging.error(f"Error parsing configuration file {config_path}: {e}")
        return None

def main():
    config = load_config()
    if not config:
        return

    ast_dir = config.get('ast_input_directory', 'ast')
    output_dir = config.get('output_directory', 'output')
    graph_output_filename = config.get('graph_config', {}).get('output_filename', 'codebase_graph.html')
    graph_output_path = Path(output_dir) / graph_output_filename

    # --- Stage 1: Find and Parse ASTs ---
    logging.info("--- Starting AST Parsing ---")
    ast_files = find_ast_files(ast_dir)
    if not ast_files:
        logging.warning(f"No AST files found in {ast_dir}. Exiting.")
        return

    all_extracted_data = {} # file_id -> extracted_data_for_file
    for ast_file_path in tqdm(ast_files, desc="Parsing ASTs"):
        try:
            with open(ast_file_path, 'r', encoding='utf-8') as f:
                ast_json_data = json.load(f)
            # Pass the original file path string for potential use in resolving paths
            extracted = extract_features_from_ast(ast_json_data, ast_file_path, config)
            if extracted and extracted.get('file_id'):
                all_extracted_data[extracted['file_id']] = extracted
            else:
                 logging.warning(f"No features extracted or file_id missing for {ast_file_path}")
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse JSON AST file {ast_file_path}: {e}")
        except Exception as e:
            logging.error(f"Error processing AST file {ast_file_path}: {e}", exc_info=True)
    logging.info(f"--- Finished AST Parsing: {len(all_extracted_data)} files processed ---")

    if not all_extracted_data:
         logging.error("No data extracted from ASTs. Cannot proceed.")
         return

    # --- Stage 2: LLM Enhancement (Optional) ---
    logging.info("--- Starting LLM Enhancement ---")
    enhanced_data = enhance_data_with_llm(all_extracted_data, config)
    logging.info("--- Finished LLM Enhancement ---")

    # --- Stage 3: Graph Building ---
    logging.info("--- Starting Graph Building ---")
    try:
        graph = build_graph(enhanced_data, config)
    except Exception as e:
        logging.error(f"Failed during graph building: {e}", exc_info=True)
        return
    logging.info("--- Finished Graph Building ---")

    # --- Stage 4: Visualization ---
    logging.info("--- Starting Graph Visualization ---")
    try:
        visualization_lib = config.get('graph_config', {}).get('visualization_library', 'pyvis')
        if visualization_lib == 'pyvis':
            visualize_pyvis(graph, graph_output_path, config)
        else:
            logging.warning(f"Visualization library '{visualization_lib}' not implemented. Only 'pyvis' is supported.")
    except Exception as e:
        logging.error(f"Failed during graph visualization: {e}", exc_info=True)
        return
    logging.info("--- Finished Graph Visualization ---")

    logging.info(f"Pipeline finished successfully. Output graph: {graph_output_path}")

if __name__ == "__main__":
    main()