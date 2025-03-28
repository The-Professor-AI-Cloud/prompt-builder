def build_prompt(inputs):
    prompt = f"""
Create a prompt using the CAPTURE formula:
- Context: {inputs.get('context')}
- Audience: {inputs.get('audience')}
- Purpose: {inputs.get('purpose')}
- Tone: {inputs.get('tone')}
- Use case: {inputs.get('use_case')}
- Relevance: {inputs.get('relevance')}
- Examples: {inputs.get('examples')}
"""
    return prompt.strip()
