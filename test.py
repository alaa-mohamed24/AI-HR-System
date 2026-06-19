import os
import re
import pandas
import pdfplumber
import json
import sqlite3
from openai import OpenAI
import streamlit as st

# ==========================================
# 1- Setup LLM
# ==========================================
client = OpenAI(
    api_key="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",
    base_url="https://api.groq.com/openai/v1" 
)

# ==========================================
# 2- Extract text
# ==========================================
def extract_text_from_pdf(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text.strip()

# ==========================================
# 3- Regex extraction
# ==========================================
def extract_email(text):
    match = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,}", text)
    return match[0].lower().strip() if match else "not found"

def extract_phone(text):
    match = re.findall(r"\+?\d[\d\s\-]{7,15}\d", text)
    return re.sub(r"[\s\-]", "" , match[0]) if match else "not found"

# ==========================================
# 4- LLM extraction
# ==========================================
def extract_with_llm(text):
    prompt = f"""
    extract the following information from this CV text :
    - name : full name of the person.
    - experience_years : total years of experience as a number (e.g. , 3 or 1.5). if fresh graduate , put 0.
    - job_title : their current or most recent role.
    - skills : extract a list of all technical skills , tools , programming languages , or professional methodologies mentioned in the CV.

    return only json in this format:

    {{
       "name" : "",
       "experience_years" : 0,
       "job_title" : "",
       "skills" : ["skill1", "skill2", "skill3"]
    }}

    CV :
    {text[:4000]}
    """
    
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content" : prompt}],
        temperature=0
    )
    
    raw_content = response.choices[0].message.content.strip()
    
    try:
        start_idx = raw_content.find('{')
        end_idx = raw_content.rfind('}') + 1
        if start_idx != -1 and end_idx != 0:
            clean_content = raw_content[start_idx:end_idx]
        else:
            clean_content = raw_content
        return json.loads(clean_content)
    except Exception as e:
        print(f"Error: Failed to parse AI output to JSON due: {e}")
        return {
            "name": "unknown", 
            "experience_years": 0, 
            "job_title": "unknown", 
            "skills": []
        }

# ==========================================
# 5- Combine everything
# ==========================================
def parse_cv(file_path):
    text = extract_text_from_pdf(file_path)
    llm_data = extract_with_llm(text)
    
    if "skills" in llm_data and isinstance(llm_data["skills"], list):
        llm_data["skills"] = ", ".join(llm_data["skills"]) if llm_data["skills"] else "not found"
    else:
        llm_data["skills"] = "not found"
        
    local_data = {
        "email": extract_email(text),
        "phone": extract_phone(text)
    }
    llm_data.update(local_data)
    return llm_data

# ==========================================
# 6- Database and table creation function
# ==========================================
def init_database():
    conn = sqlite3.connect("HR_Database.db")
    cursor = conn.cursor()
    cursor.execute("""
       CREATE TABLE IF NOT EXISTS candidates (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           file_name TEXT,
           name TEXT,
           email TEXT,
           phone TEXT,
           job_title TEXT,
           experience_years REAL,         
           skills TEXT                                                                                
        )                    
    """)
    conn.commit()
    return conn

# ==========================================
# 7- Streamlit Web Interface
# ==========================================
st.set_page_config(page_title="AI HR System", page_icon="💼", layout="centered")

st.title("💼 AI-Powered CV Parser & Screener")
st.write("Welcome! Upload multiple CVs in PDF format to automatically extract credentials and save them directly to the database.")

# Drag and drop file uploader widget
uploaded_files = st.file_uploader("Drag and drop PDF resumes here", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    db_connection = init_database()
    db_cursor = db_connection.cursor()
    
    success_count = 0
    
    for uploaded_file in uploaded_files:
        file_name = uploaded_file.name
        
        # Check if file has already been processed to avoid duplicates
        db_cursor.execute("SELECT 1 FROM candidates WHERE file_name = ?", (file_name,))
        if db_cursor.fetchone():
            st.warning(f"⚠️ Skipping: '{file_name}' (Already exists in the database).")
            continue
            
        # Spinner visual cue during background processing
        with st.spinner(f"Analyzing and parsing: {file_name} ..."):
            # Temporarily save uploaded file locally to read via pdfplumber
            with open(file_name, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Process and parse data
            candidate_info = parse_cv(file_name)
            skills_value = candidate_info.get("skills", "not found")
            
            # Cleanup temporary file
            if os.path.exists(file_name):
                os.remove(file_name)
            
            # Commit extracted fields into SQLite database table
            db_cursor.execute("""
                INSERT INTO candidates (file_name, name, email, phone, job_title, experience_years, skills)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                file_name, 
                candidate_info.get("name", "unknown"),
                candidate_info.get("email", "not found"),
                candidate_info.get("phone", "not found"),
                candidate_info.get("job_title", "unknown"),
                candidate_info.get("experience_years", 0),
                skills_value
            ))
            db_connection.commit()
            success_count += 1
            
    if success_count > 0:
        st.success(f"Process Complete! Successfully parsed and saved {success_count} new candidate profile(s).")
    
    db_connection.close()
# ==========================================
# 8- View Data and Download Section 
# ==========================================
st.write("---")
st.subheader("📊 Processed Candidates Database")

conn = init_database()
try:
    df = pd.read_sql_query("SELECT * FROM candidates", conn)
except Exception as e:
    df = pd.DataFrame()
conn.close()

if not df.empty:
    # عرض الجدول بشكل تجميلي مباشر على الشاشة
    st.dataframe(df)
    
    # تجهيز زر لتحميل البيانات كملف إكسيل/CSV
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Data as CSV (Excel)",
        data=csv,
        file_name="HR_Extracted_Candidates.csv",
        mime="text/csv",
    )
else:
    st.info("The database is currently empty. Upload CVs to see records here.")
    
