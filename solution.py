#!/usr/bin/env python3
"""
AI Assistant for Converting Business Text to Structured JSON
Powerplay AI Engineering Intern Assignment
"""

import json
import re
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from openai import AzureOpenAI

@dataclass
class MaterialOrder:
    """Schema definition for material orders"""
    material_name: str
    quantity: float
    unit: str
    project_name: Optional[str]
    location: Optional[str]
    urgency: str  # "low" | "medium" | "high"
    deadline: Optional[str]  # ISO date format


class StructuredExtractor:
    """Extracts structured data from unstructured business text using LLM"""
    
    URGENCY_KEYWORDS = {
        'high': ['urgent', 'urgently', 'asap', 'immediately', 'today', 'tomorrow', 'critical', 'emergency'],
        'medium': ['soon', 'needed', 'required', 'priority'],
        'low': ['eventually', 'when possible']
    }
    
    SCHEMA = {
        "material_name": "string",
        "quantity": "number",
        "unit": "string",
        "project_name": "string | null",
        "location": "string | null",
        "urgency": "low | medium | high",
        "deadline": "ISO date string | null"
    }
    
    def __init__(self, api_key: Optional[str] = None, model: str = None, 
                 azure_endpoint: Optional[str] = None, api_version: str = "2024-02-15-preview"):
        """Initialize with Azure OpenAI credentials"""
        self.api_key = api_key or os.getenv('AZURE_OPENAI_API_KEY')
        self.azure_endpoint = azure_endpoint or os.getenv('AZURE_OPENAI_ENDPOINT')
        self.model = model or os.getenv('AZURE_OPENAI_DEPLOYMENT') or "gpt-5"
        
        if not self.api_key:
            raise ValueError("Azure OpenAI API key required. Set AZURE_OPENAI_API_KEY env variable or pass api_key parameter")
        if not self.azure_endpoint:
            raise ValueError("Azure OpenAI endpoint required. Set AZURE_OPENAI_ENDPOINT env variable or pass azure_endpoint parameter")
        
        self.client = AzureOpenAI(
            api_key=self.api_key,
            api_version=api_version,
            azure_endpoint=self.azure_endpoint
        )
        self.system_prompt = self._build_system_prompt()
    
    def _build_system_prompt(self) -> str:
        """Build comprehensive system prompt with schema and examples"""
        return f"""You are a precise data extraction assistant for construction material orders.

Extract information into this EXACT JSON schema:
{json.dumps(self.SCHEMA, indent=2)}

CRITICAL RULES:
1. Output ONLY valid JSON, no other text
2. Use null for ANY missing information - NEVER guess or hallucinate
3. Extract quantities as numbers (e.g., 25, 120, 350)
4. Keep material names concise but descriptive
5. Dates must be ISO format (YYYY-MM-DD) or null
6. Urgency: infer from keywords or deadline, default to "low"
7. Include ONLY the 7 schema fields, no extras

EXAMPLES:

Input: "Create 25mm steel bars, 120 units for Project Phoenix, required before 15th March"
Output:
{{
  "material_name": "25mm steel bars",
  "quantity": 120,
  "unit": "units",
  "project_name": "Project Phoenix",
  "location": null,
  "urgency": "medium",
  "deadline": "{datetime.now().year}-03-15"
}}

Input: "Need 350 bags of Ultratech Cement 50kg for the site Mumbai-West urgently in 7 days"
Output:
{{
  "material_name": "Ultratech Cement 50kg",
  "quantity": 350,
  "unit": "bags",
  "project_name": null,
  "location": "Mumbai-West",
  "urgency": "high",
  "deadline": "{(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')}"
}}

Input: "Order 12 truckloads of river sand for Bangalore Metro Phase 2 by April end"
Output:
{{
  "material_name": "river sand",
  "quantity": 12,
  "unit": "truckloads",
  "project_name": "Bangalore Metro Phase 2",
  "location": null,
  "urgency": "medium",
  "deadline": "{datetime.now().year}-04-30"
}}

Input: "Get some bricks"
Output:
{{
  "material_name": "bricks",
  "quantity": null,
  "unit": null,
  "project_name": null,
  "location": null,
  "urgency": "low",
  "deadline": null
}}

Now extract from the user's input."""

    def _extract_json_from_response(self, response: str) -> Dict:
        """Extract JSON from LLM response, handling markdown code blocks"""
        # Try direct parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Try extracting from markdown code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try finding first { to last }
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(response[start:end+1])
            except json.JSONDecodeError:
                pass
        
        raise ValueError(f"Could not extract valid JSON from response: {response[:200]}")
    
    def _infer_urgency(self, text: str, deadline: Optional[str]) -> str:
        """Infer urgency from text keywords and deadline"""
        text_lower = text.lower()
        
        # Check keywords
        for urgency_level, keywords in self.URGENCY_KEYWORDS.items():
            if any(keyword in text_lower for keyword in keywords):
                return urgency_level
        
        # Check deadline proximity
        if deadline:
            try:
                deadline_date = datetime.fromisoformat(deadline)
                days_until = (deadline_date - datetime.now()).days
                
                if days_until < 7:
                    return 'high'
                elif days_until < 30:
                    return 'medium'
                else:
                    return 'low'
            except (ValueError, TypeError):
                pass
        
        return 'low'
    
    def _parse_relative_date(self, text: str) -> Optional[str]:
        """Parse relative dates like 'in 7 days', 'by April end'"""
        text_lower = text.lower()
        
        # Pattern: "in X days"
        days_match = re.search(r'in\s+(\d+)\s+days?', text_lower)
        if days_match:
            days = int(days_match.group(1))
            target_date = datetime.now() + timedelta(days=days)
            return target_date.strftime('%Y-%m-%d')
        
        # Pattern: "by [month] end"
        month_end_match = re.search(r'by\s+(\w+)\s+end', text_lower)
        if month_end_match:
            month_name = month_end_match.group(1)
            month_map = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4,
                'may': 5, 'june': 6, 'july': 7, 'august': 8,
                'september': 9, 'october': 10, 'november': 11, 'december': 12
            }
            if month_name in month_map:
                month = month_map[month_name]
                year = datetime.now().year
                # Get last day of month
                if month == 12:
                    last_day = 31
                else:
                    from calendar import monthrange
                    last_day = monthrange(year, month)[1]
                return f"{year}-{month:02d}-{last_day:02d}"
        
        return None
    
    def _validate_and_fix(self, data: Dict, original_text: str) -> Dict:
        """Validate output against schema and fix common issues"""
        # Ensure all required fields exist
        required_fields = ['material_name', 'quantity', 'unit', 'project_name', 
                          'location', 'urgency', 'deadline']
        
        for field in required_fields:
            if field not in data:
                data[field] = None
        
        # Remove extra fields
        data = {k: v for k, v in data.items() if k in required_fields}
        
        # Type validation and fixing
        # quantity must be number or null
        if data['quantity'] is not None:
            try:
                data['quantity'] = float(data['quantity'])
            except (ValueError, TypeError):
                data['quantity'] = None
        
        # urgency must be valid enum
        if data['urgency'] not in ['low', 'medium', 'high']:
            data['urgency'] = self._infer_urgency(original_text, data.get('deadline'))
        
        # deadline must be valid ISO date or null
        if data['deadline']:
            if isinstance(data['deadline'], str):
                # Validate ISO format
                try:
                    datetime.fromisoformat(data['deadline'])
                except ValueError:
                    # Try to parse it
                    parsed_date = self._parse_relative_date(original_text)
                    data['deadline'] = parsed_date
            else:
                data['deadline'] = None
        
        # String fields should be strings or null
        for field in ['material_name', 'unit', 'project_name', 'location']:
            if data[field] is not None and not isinstance(data[field], str):
                data[field] = str(data[field])
            # Clean empty strings to null
            if data[field] == '' or data[field] == 'null':
                data[field] = None
        
        return data
    
    def extract(self, text: str, max_retries: int = 2) -> Dict:
        """
        Extract structured data from unstructured text
        
        Args:
            text: Input business text
            max_retries: Maximum retry attempts on validation failure
            
        Returns:
            Dictionary conforming to MaterialOrder schema
        """
        for attempt in range(max_retries + 1):
            try:
                # Add delay between retries to avoid rate limits
                if attempt > 0:
                    wait_time = attempt * 2
                    print(f"  Retry {attempt} after {wait_time}s...")
                    time.sleep(wait_time)
                
                # Call LLM using new API
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": f"Extract material order information from: {text}\n\nRespond with ONLY valid JSON, no other text."}
                    ],
                    max_completion_tokens=2000  # Increased for GPT-5
                )
                
                # Extract response
                raw_output = response.choices[0].message.content
                
                # Debug: print response details (only on first attempt)
                if attempt == 0:
                    print(f"  Response length: {len(raw_output) if raw_output else 0}")
                
                if not raw_output or not raw_output.strip():
                    if attempt < max_retries:
                        print(f"  Empty response, retrying...")
                        continue
                    raise ValueError("Empty response from model after all retries")
                
                raw_output = raw_output.strip()
                
                # Parse JSON
                data = self._extract_json_from_response(raw_output)
                
                # Validate and fix
                data = self._validate_and_fix(data, text)
                
                print(f"  ✓ Success")
                return data
                
            except Exception as e:
                if attempt == max_retries:
                    # Final fallback: return minimal valid structure
                    print(f"  ✗ Failed: {str(e)[:100]}")
                    return {
                        'material_name': None,
                        'quantity': None,
                        'unit': None,
                        'project_name': None,
                        'location': None,
                        'urgency': 'low',
                        'deadline': None,
                        'error': str(e)
                    }
                # Retry
                continue
    
    def batch_extract(self, texts: List[str], output_file: str = 'outputs.json') -> List[Dict]:
        """Extract structured data from multiple texts with incremental saving"""
        results = []
        for i, text in enumerate(texts):
            print(f"Processing {i+1}/{len(texts)}: {text[:60]}...")
            result = self.extract(text)
            result['input_text'] = text
            results.append(result)
            
            # Save incrementally after each item
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        
        return results


def load_inputs(file_path: str) -> List[str]:
    """Load input texts from file (one per line)"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def save_outputs(outputs: List[Dict], file_path: str):
    """Save outputs to JSON file"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(outputs, f, indent=2, ensure_ascii=False)


def main():
    """Main execution function"""
    import sys
    
    # Check for API key and endpoint
    if not os.getenv('AZURE_OPENAI_API_KEY'):
        print("ERROR: Please set AZURE_OPENAI_API_KEY environment variable")
        print("Example: export AZURE_OPENAI_API_KEY='your-key-here'")
        sys.exit(1)
    
    if not os.getenv('AZURE_OPENAI_ENDPOINT'):
        print("ERROR: Please set AZURE_OPENAI_ENDPOINT environment variable")
        print("Example: export AZURE_OPENAI_ENDPOINT='https://your-resource.openai.azure.com/'")
        sys.exit(1)
    
    # Initialize extractor
    print("Initializing AI Extractor...")
    print(f"Using deployment: {os.getenv('AZURE_OPENAI_DEPLOYMENT') or 'gpt5'}")
    extractor = StructuredExtractor()
    
    # Load inputs
    input_file = 'test_inputs.txt'
    if not os.path.exists(input_file):
        print(f"ERROR: {input_file} not found")
        sys.exit(1)
    
    print(f"Loading inputs from {input_file}...")
    texts = load_inputs(input_file)
    print(f"Loaded {len(texts)} test cases")
    
    # Process
    print("\nProcessing inputs...")
    results = extractor.batch_extract(texts)
    
    # Save outputs
    output_file = 'outputs.json'
    save_outputs(results, output_file)
    print(f"\n✓ Saved {len(results)} results to {output_file}")
    
    # Print summary
    print("\nSummary:")
    errors = [r for r in results if 'error' in r]
    print(f"  Total processed: {len(results)}")
    print(f"  Successful: {len(results) - len(errors)}")
    print(f"  Errors: {len(errors)}")
    
    if errors:
        print("\nFailed cases:")
        for err in errors:
            print(f"  - {err['input_text'][:60]}...")


if __name__ == '__main__':
    main()
