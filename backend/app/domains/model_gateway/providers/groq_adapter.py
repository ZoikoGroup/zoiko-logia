import os
from groq import Groq

class GroqAdapter:
    """Groq provider adapter.
    
    Reads GROQ_API_KEY from environment.
    """
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        if self.api_key:
            self.client = Groq(api_key=self.api_key)
        else:
            self.client = None

    def complete(self, prompt: str, model: str = "llama3-8b-8192") -> str:
        if not self.client:
            return "[Error: GROQ_API_KEY not found in environment. Please add it to backend/.env]"
        
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are Kriton™, a helpful professional advisor. Answer based only on the provided context. If no context is provided, state that you cannot answer without sufficient source material."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0 # Deterministic routing/answering per governance
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[Error connecting to Groq API: {str(e)}]"
