import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
OPENAI_KEY = os.getenv('OPENAI_API_KEY')

class LLMType:
    OPENAI = 'openAI'

class Models:
    GPT3 = 'gpt-3.5-turbo-16k'
    GPT4 = 'gpt-4'

class LLM:
    def __init__(self, llm_type=LLMType.OPENAI, model=Models.GPT4):
        self.type = llm_type
        self.model = model
        self.openai_key = os.getenv('OPENAI_API_KEY')

    def chat(self, message, functions=None):
        if self.type == LLMType.OPENAI:
            message = [self._to_gpt_msg(message)]
            return self._call_openai(message, functions)
        else:
            raise ValueError("Unsupported LLM type.")

    def _to_gpt_msg(self, data):
        context_msg = str(data)
        return {
            "role": 'system',
            "content": context_msg
        }

    def _call_openai(self, message, functions=None):
        url = 'https://api.openai.com/v1/chat/completions'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.openai_key}'
        }
        data = {
            "model": self.model,
            "messages": message,
            "temperature": 0.6
        }
        if functions:
            data.update({
                "functions": functions,
                "function_call": 'auto',
            })

        response = requests.post(url, headers=headers, data=json.dumps(data))
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"error": "Failed to decode JSON response."}

    def get_word_limit(self):
        return 2000