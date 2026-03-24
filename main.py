import os
import json
import pandas as pd
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import anthropic
import uvicorn
from io import StringIO
import tempfile

app = FastAPI()

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html") as f:
        return f.read()

@app.get("/sample")
async def get_sample():
    try:
        df = pd.read_csv("data/sample_expenses.csv")
        return df.to_dict(orient="records")
    except Exception:
        return [
            {"date": "2024-01-15", "vendor": "Valvoline", "amount": 89.50, "description": "Oil change for truck 442", "category": ""},
            {"date": "2024-01-16", "vendor": "Home Depot", "amount": 245.99, "description": "Hydraulic fittings and hoses", "category": "parts"},
            {"date": "2024-01-18", "vendor": "Shell", "amount": 67.84, "description": "Fuel - service route", "category": ""}
        ]

@app.post("/process")
async def process_expenses(file: UploadFile = File(...)):
    if not file.filename.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only CSV and Excel files supported")
    
    try:
        content = await file.read()
        
        if file.filename.endswith('.csv'):
            df = pd.read_csv(StringIO(content.decode('utf-8')))
        else:
            df = pd.read_excel(content)
        
        # Prepare data for Claude
        expenses_text = df.to_csv(index=False)
        
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        
        system_prompt = """You are an expense processing assistant for PIRTEK USA, a field service company. Analyze the uploaded expense data and:

1. Categorize each expense into proper GL codes:
   - 6100: Vehicle Maintenance
   - 5200: Parts/Inventory  
   - 7100: Labor
   - 6200: Fuel
   - 6150: Equipment Repairs
   - 6300: Insurance
   - 6400: Permits/Licenses
   - 6500: General Operating

2. Clean up vendor names and descriptions
3. Validate amounts and dates
4. Add estimated tax amounts (assume 8.5% sales tax where applicable)
5. Generate receipt numbers where missing

Return ONLY a CSV format with these exact columns:
Date,Vendor,Amount,GL_Code,Category,Description,Tax_Amount,Receipt_Number

Make the data clean and ERP-ready."""

        message = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-3-sonnet-20240229"),
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Process this expense data:\n\n{expenses_text}"}]
        )
        
        processed_csv = message.content[0].text.strip()
        
        # Save processed file
        output_filename = f"siteline_import_{file.filename.split('.')[0]}.csv"
        with open(output_filename, 'w') as f:
            f.write(processed_csv)
        
        # Parse for preview
        preview_df = pd.read_csv(StringIO(processed_csv))
        
        return {
            "success": True,
            "original_count": len(df),
            "processed_count": len(preview_df),
            "preview": preview_df.head(10).to_dict(orient="records"),
            "download_filename": output_filename
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

@app.get("/download/{filename}")
async def download_file(filename: str):
    if not os.path.exists(filename):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(filename, filename=filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)