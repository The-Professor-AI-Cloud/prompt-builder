import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
import os
from io import BytesIO
from fpdf import FPDF
import base64
import requests

# Load environment variables
load_dotenv()
client = OpenAI()

# Page config
st.set_page_config(
    page_title="Interactive Prompt Builder",
    page_icon="logo.png",
    layout="centered"
)

# Load logo as base64 for inline HTML rendering
def get_base64_logo(path):
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode()
    return f"data:image/png;base64,{encoded}"

logo_data = get_base64_logo("logo.png")

# CSS styling
st.markdown(f"""
<style>
    html, body, [class*="css"] {{
        font-family: 'Helvetica Neue', sans-serif;
        background-color: #ffffff;
        color: #222;
    }}
    .header-container {{
        display: flex;
        align-items: center;
        gap: 1rem;
        margin-bottom: 2rem;
    }}
    .logo {{
        height: 40px;
        margin-top: -6px;
    }}
    .main-title {{
        font-size: 32px;
        font-weight: 600;
        margin: 0;
    }}
    .step-title {{
        font-size: 22px;
        font-weight: 600;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
    }}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown(f"""
<div class="header-container">
  <img src="{logo_data}" class="logo">
  <h1 class="main-title">Interactive Prompt Builder</h1>
</div>
""", unsafe_allow_html=True)

# State init
if 'step' not in st.session_state: st.session_state.step = 1
if 'goal' not in st.session_state: st.session_state.goal = ""
if 'style' not in st.session_state: st.session_state.style = ""
if 'questions' not in st.session_state: st.session_state.questions = []
if 'answers' not in st.session_state: st.session_state.answers = {}
if 'generated_prompt' not in st.session_state: st.session_state.generated_prompt = ""
if 'history' not in st.session_state: st.session_state.history = []
if 'show_history' not in st.session_state: st.session_state.show_history = False
if 'show_feedback' not in st.session_state: st.session_state.show_feedback = False

# Prompt history toggle
if st.session_state.history:
    if st.button("📚 View Prompt History"):
        st.session_state.show_history = not st.session_state.show_history

if st.session_state.show_history and st.session_state.history:
    st.markdown("### 📖 Prompt History")
    for i, prompt in enumerate(st.session_state.history):
        st.markdown(f"**Prompt {i+1}:** {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
        with st.expander("View Full Prompt"):
            st.code(prompt)

    if st.button("📄 Download All Prompts as PDF"):
        pdf = FPDF()
        pdf.add_page()
        font_path = os.path.join(os.getcwd(), "DejaVuSans.ttf")
        if not os.path.isfile(font_path):
            st.error(f"Font file not found: {font_path}")
        else:
            pdf.add_font("DejaVu", "", font_path, uni=True)
            pdf.set_font("DejaVu", size=12)
            for i, p in enumerate(st.session_state.history, 1):
                pdf.multi_cell(0, 10, f"Prompt {i}:")
                pdf.multi_cell(0, 10, p)
                pdf.ln()
            buffer = BytesIO()
            pdf_output = pdf.output(dest='S').encode('latin1')
            buffer.write(pdf_output)
            buffer.seek(0)
            st.download_button("📥 Download PDF", data=buffer, file_name="prompts.pdf", mime="application/pdf")

# Step 1: Goal + Style
if st.session_state.step == 1:
    st.markdown("### Step 1: Define your goal")
    st.session_state.goal = st.text_area("What do you want to achieve with AI?", placeholder="e.g., Write a blog post about healthy eating")
    st.session_state.style = st.selectbox("Choose a prompt style:", ["Creative", "Technical", "Conversational", "Concise", "Formal", "Friendly"])
    if st.button("Continue") and st.session_state.goal.strip():
        with st.spinner("Analysing your request..."):
            prompt = f"""
You are a helpful AI prompt engineer.

The user wants to do the following task:
{st.session_state.goal}

Based on this, list up to 5 short, specific questions you need to ask the user before crafting the best possible AI prompt.
If no questions are needed, just return: NONE.

Return only the questions in plain text, one per line.
"""
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an expert prompt engineer."},
                    {"role": "user", "content": prompt}
                ]
            )
            content = response.choices[0].message.content.strip()
            if content.upper() == "NONE":
                st.session_state.step = 3
            else:
                st.session_state.questions = content.split("\n")
                st.session_state.step = 2
        st.rerun()

# Step 2: Clarifying questions
elif st.session_state.step == 2:
    st.markdown("### Step 2: Clarify details (optional)")
    answer_all_with_gpt = st.checkbox("Let GPT Answer all questions")
    with st.form("followups"):
        for q in st.session_state.questions:
            col1, col2 = st.columns([4, 1])
            with col1:
                default = "Let GPT Answer" if answer_all_with_gpt else ""
                user_input = st.text_input(q, value=default)
                st.session_state.answers[q] = user_input
            with col2:
                if st.checkbox("Let GPT Answer", key=f"gpt_{q}"):
                    st.session_state.answers[q] = "Let GPT Answer"
        submitted = st.form_submit_button("Generate Prompt")
        if submitted:
            st.session_state.step = 3
            st.rerun()

# Step 3: Final prompt
elif st.session_state.step == 3:
    st.markdown("### Step 3: Your final prompt")
    with st.spinner("Crafting your prompt..."):
        filled_answers = "\n".join([f"- {q}: {a}" for q, a in st.session_state.answers.items()])
        full_context = f"""
You are an expert AI prompt engineer.

The user wants to:
{st.session_state.goal}

Here are some clarifying details:
{filled_answers}

Preferred prompt style: {st.session_state.style}

For any answers marked 'Let GPT Answer' or left blank, fill in appropriate defaults.

Your task is to write a clear, detailed prompt that the user can copy and paste into ChatGPT or another AI tool.
Do not respond to the request. Instead, write the prompt that should be used.
If image generation is involved, write for Midjourney or DALL·E.
Only output the final prompt.
"""
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert prompt engineer."},
                {"role": "user", "content": full_context}
            ]
        )
        final_prompt = response.choices[0].message.content.strip()
        st.session_state.generated_prompt = final_prompt
        st.session_state.history.append(final_prompt)

    st.text_area("Copy Your Prompt:", value=st.session_state.generated_prompt, height=300)
    st.download_button("📥 Download Prompt", data=st.session_state.generated_prompt, file_name="prompt.txt", mime="text/plain")
    st.markdown("✅ Use Ctrl+C or Cmd+C to copy the prompt above.")

    if st.button("➕ Start Over"):
        st.session_state.step = 1
        st.session_state.goal = ""
        st.session_state.questions = []
        st.session_state.answers = {}
        st.session_state.generated_prompt = ""
        st.rerun()

# Feedback Button at Bottom
st.markdown("---")
if st.button("💬 Send Feedback"):
    st.session_state.show_feedback = not st.session_state.get("show_feedback", False)

if st.session_state.get("show_feedback", False):
    st.markdown("### 💬 Feedback")
    with st.form("feedback_form"):
        name = st.text_input("Your name (optional)")
        email = st.text_input("Your email (optional)")
        message = st.text_area("Your message")
        submitted = st.form_submit_button("Send Feedback")
        if submitted:
            if not message.strip():
                st.warning("Please enter a message before submitting.")
            else:
                response = requests.post(
                    "https://formspree.io/f/mgvalkbb",
                    data={"name": name, "email": email, "message": message}
                )
                if response.status_code == 200:
                    st.success("Thanks for your feedback! ✅")
                else:
                    st.error("Something went wrong. Please try again later.")
