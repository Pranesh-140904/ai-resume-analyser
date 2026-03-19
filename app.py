import os
import json
import fitz  # PyMuPDF
from flask import Flask, render_template, request, jsonify, session
from groq import Groq

app = Flask(__name__)
app.secret_key = "resume_analyser_secret_key_2024"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─── PASTE YOUR FREE GROQ API KEY HERE ───────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "your-groq-api-key-here")"
# ─────────────────────────────────────────────────────────────────────────────

client = Groq(api_key=GROQ_API_KEY)


# ─── Helper: Extract text from PDF ───────────────────────────────────────────
def extract_text_from_pdf(filepath):
    text = ""
    with fitz.open(filepath) as doc:
        for page in doc:
            text += page.get_text()
    return text.strip()


# ─── Helper: Call Groq AI ─────────────────────────────────────────────────────
def analyse_with_groq(resume_text, job_desc=""):
    jd_section = (
        f"\n\nJOB DESCRIPTION:\n{job_desc}"
        if job_desc
        else "\n\nNo job description provided. Set job_match_score to null."
    )

    prompt = f"""You are an expert resume analyser and career coach. Analyse the resume below and return ONLY a valid JSON object — no markdown, no explanation, nothing else.

RESUME:
{resume_text}
{jd_section}

Return exactly this JSON structure:
{{
  "overall_score": <number 0-100>,
  "ats_score": <number 0-100>,
  "skills_score": <number 0-100>,
  "job_match_score": <number 0-100 or null>,
  "summary": "<2-3 sentence executive summary>",
  "skills_found": ["skill1", "skill2"],
  "missing_skills": ["skill1", "skill2"],
  "power_keywords": ["keyword1", "keyword2"],
  "ats_checks": [
    {{"label": "Check name", "status": "pass", "note": "short note"}}
  ],
  "strengths": ["strength1", "strength2"],
  "weaknesses": ["weakness1", "weakness2"],
  "suggestions": ["suggestion1", "suggestion2"]
}}

ATS checks must include: Contact Info Present, Professional Summary, Quantified Achievements, Action Verbs Used, Standard Section Headings, No Tables/Images, Consistent Date Format, Keywords Density, Education Section, File Format Friendly.
Return 5-8 items for skills_found, 3-5 for others.
IMPORTANT: Return ONLY the JSON object. No extra text."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=2000,
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert resume analyser. Always respond with valid JSON only. No markdown, no explanation."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        raw = response.choices[0].message.content
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(cleaned)
        return result, None
    except json.JSONDecodeError as e:
        return None, f"AI returned invalid response: {str(e)}"
    except Exception as e:
        return None, str(e)


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyse", methods=["POST"])
def analyse():
    job_desc = request.form.get("job_desc", "").strip()
    resume_file = request.files.get("resume")

    if not resume_file or resume_file.filename == "":
        return render_template("index.html", error="Please upload a resume file.")

    filename = resume_file.filename
    if not filename.lower().endswith((".pdf", ".txt")):
        return render_template("index.html", error="Only PDF or TXT files are supported.")

    filepath = os.path.join(UPLOAD_FOLDER, filename)
    resume_file.save(filepath)

    try:
        if filename.lower().endswith(".pdf"):
            resume_text = extract_text_from_pdf(filepath)
        else:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                resume_text = f.read()
    except Exception as e:
        return render_template("index.html", error=f"Could not read file: {str(e)}")

    if not resume_text or len(resume_text) < 50:
        return render_template("index.html", error="Resume text is too short or could not be extracted.")

    result, error = analyse_with_groq(resume_text, job_desc)
    if error:
        return render_template("index.html", error=f"AI Error: {error}")

    session["resume_text"] = resume_text[:4000]
    session["analysis"] = result

    return render_template("result.html", result=result, filename=filename, has_jd=bool(job_desc))


@app.route("/chat")
def chat():
    if "resume_text" not in session:
        return render_template("index.html", error="Please analyse a resume first.")
    return render_template("chat.html")


@app.route("/chat/message", methods=["POST"])
def chat_message():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    history = data.get("history", [])

    resume_text = session.get("resume_text", "")
    analysis = session.get("analysis", {})

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    system_prompt = f"""You are a helpful resume coach. You have analysed this resume:

RESUME:
{resume_text[:3000]}

SCORES: Overall={analysis.get('overall_score')}, ATS={analysis.get('ats_score')}, Skills={analysis.get('skills_score')}

RULES FOR YOUR REPLIES:
- Keep replies SHORT (3-5 lines max)
- NO bullet points, NO numbered lists
- NO markdown like **bold** or ## headers
- Write in plain simple sentences only
- Be direct and friendly"""
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=800,
            temperature=0.7,
            messages=messages
        )
        reply = response.choices[0].message.content
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)