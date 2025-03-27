import google.generativeai as genai
import logging
import time
from tqdm import tqdm
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_summary_from_gemini(model, prompt, max_retries=3, delay=5):
    """Sends prompt to Gemini using the model, handles retries and potential errors."""
    retries = 0

    while retries < max_retries:
        try:
            response = model.generate_content(
                contents=prompt
            )

            if response.prompt_feedback and response.prompt_feedback.block_reason:
                logging.warning(f"Gemini prompt blocked: {response.prompt_feedback.block_reason}. Prompt: {prompt[:100]}...")
                return "[LLM prompt blocked]"

            if not response.text:
                logging.warning(f"Gemini returned empty content. Prompt: {prompt[:100]}...")
                return None

            summary = response.text.strip()
            if summary.lower().startswith("summary:"):
                summary = summary[len("summary:"):].strip()
            return summary

        except Exception as e:
            retries += 1
            logging.warning(f"Gemini API call failed (Attempt {retries}/{max_retries}): {e}")
            time.sleep(delay * (retries + 1))

        if retries >= max_retries:
            logging.error(f"Max retries reached for Gemini API call. Prompt: {prompt[:100]}...")
            return None
    return None

def enhance_data_with_llm(extracted_data, config):
    """Adds descriptions/summaries using Gemini."""
    llm_conf = config.get('llm_config', {})
    if not llm_conf.get('enabled', False):
        logging.info("LLM Enhancement is disabled in config.")
        return extracted_data

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        api_key = llm_conf.get('api_key')
        if api_key:
            logging.warning("Using Gemini API key from config.yaml. Consider using environment variables (GEMINI_API_KEY) for better security.")
        else:
            logging.error("LLM is enabled but GEMINI_API_KEY environment variable is not set and api_key is missing in config.")
            return extracted_data

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        logging.info("Gemini client initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize Gemini client: {e}")
        return extracted_data

    # --- Enhance Entities ---
    logging.info("Enhancing entities...")
    entity_ids = list(extracted_data.get('entities', {}).keys())
    for entity_id in tqdm(entity_ids, desc="Enhancing Entities"):
        entity = extracted_data['entities'][entity_id]
        try:
            # --- Prepare context for prompt ---
            decorators = extracted_data.get('decorators', {}).get(entity_id, [])
            decorators_str = ', '.join([f"@{d['name']}{d['arguments_str']}" for d in decorators]) or "None"

            dependencies = extracted_data.get('dependencies', {}).get(entity_id, [])
            dependencies_str = ', '.join([f"{d['name']}: {d['type']}" for d in dependencies]) or "None"

            entity_methods = [m for m_id, m in extracted_data.get('methods', {}).items() if m.get('entity_id') == entity_id]
            methods_str = ', '.join([m['name'] + '()' for m in entity_methods]) or "None"

            prompt = f"Summarize the role of {entity.get('kind', 'Unknown')} '{entity.get('name', 'Unknown')}' with decorators: {decorators_str}, dependencies: {dependencies_str}, and methods: {methods_str}"

            summary = get_summary_from_gemini(model, prompt, max_retries=3, delay=2)
            if summary:
                entity['description'] = summary
            else:
                entity['description'] = "[LLM summary failed or unavailable]"

            time.sleep(2)  # Rate limiting

        except Exception as e:
            logging.error(f"Error enhancing entity {entity_id}: {e}", exc_info=True)
            entity['description'] = "[LLM enhancement error]"

    # --- Enhance Methods ---
    logging.info("Enhancing methods...")
    method_ids = list(extracted_data.get('methods', {}).keys())
    for method_id in tqdm(method_ids, desc="Enhancing Methods"):
        method = extracted_data['methods'][method_id]
        try:
            # --- Prepare context for prompt ---
            params_str = ', '.join([f"{p['name']}: {p['type']}" for p in method.get('parameters', [])])
            signature = f"{'async ' if method.get('is_async') else ''}{method.get('name', 'unknown')}({params_str}): {method.get('return_type', 'any')}"

            decorators = extracted_data.get('decorators', {}).get(method_id, [])
            decorators_str = ', '.join([f"@{d['name']}{d['arguments_str']}" for d in decorators]) or "None"

            prompt = f"Summarize the purpose of method with signature '{signature}' and decorators: {decorators_str}"

            summary = get_summary_from_gemini(model, prompt, max_retries=3, delay=2)
            if summary:
                method['summary'] = summary
            else:
                method['summary'] = "[LLM summary failed or unavailable]"

            time.sleep(2)  # Rate limiting

        except Exception as e:
            logging.error(f"Error enhancing method {method_id}: {e}", exc_info=True)
            method['summary'] = "[LLM enhancement error]"

    logging.info("LLM Enhancement finished.")
    return extracted_data