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

# Internal model — do not expose to users
_MODEL = "gpt-4.1"

# Page config
st.set_page_config(
    page_title="Interactive Prompt Builder",
    page_icon="favicon.ico",
    layout="centered"
)

# ─── Logo ─────────────────────────────────────────────────────────────────────
def get_base64_logo(path):
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    ext = path.split(".")[-1].lower()
    mime = {"ico": "image/x-icon", "png": "image/png", "jpg": "image/jpeg"}.get(ext, f"image/{ext}")
    return f"data:{mime};base64,{encoded}"

logo_path = "favicon.ico" if os.path.isfile("favicon.ico") else "logo.png"
logo_data = get_base64_logo(logo_path)

# ─── CSS ──────────────────────────────────────────────────────────────────────
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
        margin-bottom: 1.5rem;
    }}
    .logo {{ height: 48px; margin-top: -6px; }}
    .main-title {{ font-size: 32px; font-weight: 600; margin: 0; }}
    .rating-box {{
        background-color: #f0f4ff;
        border-left: 4px solid #4361ee;
        padding: 1rem 1.25rem;
        border-radius: 6px;
        margin-top: 1rem;
    }}
    .prompt-output {{
        background: #f9f9f9;
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        padding: 1rem;
        font-family: 'Courier New', monospace;
        font-size: 13px;
        white-space: pre-wrap;
        margin-bottom: 1rem;
    }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="header-container">
  <img src="{logo_data}" class="logo">
  <h1 class="main-title">Interactive Prompt Builder</h1>
</div>
""", unsafe_allow_html=True)

# ─── Mode ─────────────────────────────────────────────────────────────────────
mode = st.radio("Mode", ["📝 Text Prompt", "🎨 Image Prompt"], horizontal=True,
                label_visibility="collapsed")

# ─── Image tool definitions ───────────────────────────────────────────────────
IMAGE_TOOLS = {
    "Midjourney": {
        "description": "Comma-separated phrases + parameter flags (--ar, --style, --v, --chaos)",
        "supports_negative": False,
        "system": """You are a Midjourney expert who has written thousands of high-performing prompts.
You know that Midjourney responds best to:
- Vivid, evocative noun phrases and adjectives (NOT full sentences)
- A clear subject → environment → style → mood → technical sequence
- Specific artist references or aesthetic movements when relevant
- Parameters at the end: --ar, --style raw, --v 6.1, --chaos, --stylize

Structure every prompt as:
[subject and action], [environment and setting], [lighting and atmosphere], [art style and medium], [colour palette], [technical details and quality], --[parameters]""",
    },
    "DALL·E 3": {
        "description": "Rich natural language — narrative and descriptive",
        "supports_negative": False,
        "system": """You are a DALL·E 3 expert. DALL·E 3 is trained on natural language and rewards:
- Clear, vivid narrative descriptions written as complete, flowing sentences
- Explicit specification of composition, perspective, and framing
- Detailed lighting and atmosphere description
- Style references (e.g. "in the style of a 1970s National Geographic photograph")
- Specific mention of what should NOT dominate the image (DALL·E 3 doesn't use negative prompts, so weave exclusions into the description)

Write the prompt as 2-4 rich descriptive sentences. Be precise and leave nothing ambiguous.""",
    },
    "Stable Diffusion": {
        "description": "Weighted keywords, quality boosters, negative prompts",
        "supports_negative": True,
        "system": """You are a Stable Diffusion expert who produces prompts for SDXL and SD 1.5/2.1.
You know that SD responds best to:
- Comma-separated keywords ordered by importance (most important first)
- Quality boosters: (masterpiece:1.2), (best quality:1.3), (highly detailed:1.2), sharp focus, 8k, HDR
- Parentheses for emphasis with weights: (cinematic lighting:1.4), (intricate details:1.2)
- Artist references where appropriate: "by Greg Rutkowski, Artgerm"
- Explicit camera/lens details for photorealism: "shot on Sony A7R IV, 85mm lens, f/1.8"

Format: positive prompt first, then on a new line "Negative prompt: [list of things to avoid]"
Always include in negative: "blurry, low quality, bad anatomy, watermark, signature, ugly, deformed" plus any user-specified exclusions.""",
    },
    "Imagen / Firefly": {
        "description": "Clean descriptive language with medium and content type",
        "supports_negative": False,
        "system": """You are an expert at writing prompts for Google Imagen and Adobe Firefly.
These models respond best to:
- Specifying the content type and medium upfront: "A photograph of...", "A digital illustration of...", "An oil painting of..."
- Precise, photographic language: aperture, depth of field, focal length, sensor style
- Clear compositional direction: foreground/background, rule of thirds, symmetry
- Explicit colour grading references: "warm golden tones", "cool desaturated palette", "Kodak Portra 400 film"
- For Firefly: reference specific Adobe Stock aesthetic styles where relevant

Write in clean, precise sentences. Avoid special syntax or weightings — these models prefer natural language.""",
    },
    "Nano Banana": {
        "description": "Bold, surreal, maximally expressive prompts",
        "supports_negative": False,
        "system": """You are a creative director specialising in Nano Banana image generation.
Nano Banana thrives on:
- Bold, unexpected juxtapositions and surreal combinations
- Highly specific sensory details: textures, smells, sounds translated visually
- Cinematic references blended with fine art traditions
- Maximum visual specificity — no vague words like "beautiful" or "interesting"
- Unusual perspective choices and compositional experiments
- Rich, layered descriptions that reward close inspection

Write the most vivid, original, cinematically compelling prompt possible. Surprise with the specificity.""",
    },
}

# ─── Session state defaults ───────────────────────────────────────────────────
defaults = {
    "step": 1, "goal": "", "style": "",
    "questions": [], "answers": {},
    "generated_prompt": "", "prompt_rating": "",
    "history": [], "show_history": False, "show_feedback": False,
    "img_step": 1, "img_tool": "Midjourney",
    "img_subject": "", "img_art_style": "", "img_mood": "",
    "img_lighting": "", "img_colors": "", "img_composition": "",
    "img_extra": "", "img_negative": "",
    "img_generated": "", "img_rating": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# HELPER — call model
# ══════════════════════════════════════════════════════════════════════════════
def call_model(system: str, user: str) -> str:
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    return response.choices[0].message.content.strip()


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE PROMPT MODE
# ══════════════════════════════════════════════════════════════════════════════
if mode == "🎨 Image Prompt":
    st.markdown("#### 🎨 Image Prompt Builder")
    st.caption("Generates prompts optimised for each image generation tool.")

    if st.session_state.img_step == 1:
        st.markdown("**Step 1 — Describe your image**")

        st.session_state.img_tool = st.selectbox("Target tool:", list(IMAGE_TOOLS.keys()))
        tool = IMAGE_TOOLS[st.session_state.img_tool]
        st.caption(f"💡 {tool['description']}")

        st.session_state.img_subject = st.text_area(
            "Describe your image:",
            placeholder="e.g. A futuristic city skyline at dusk, flying cars, neon reflections on wet streets"
        )

        col1, col2 = st.columns(2)
        with col1:
            st.session_state.img_art_style = st.selectbox("Art style:", [
                "Photorealistic", "Cinematic", "Oil painting", "Watercolour",
                "Anime / Manga", "Digital art", "Illustration", "Concept art",
                "Abstract", "Pixel art", "Pencil sketch", "3D render"
            ])
            st.session_state.img_mood = st.selectbox("Mood:", [
                "Dramatic", "Serene", "Mysterious", "Joyful", "Melancholic",
                "Epic", "Ethereal", "Gritty", "Whimsical", "Tense"
            ])
            st.session_state.img_lighting = st.selectbox("Lighting:", [
                "Golden hour", "Studio lighting", "Moody / low-key", "Bright and airy",
                "Neon glow", "Soft diffused", "Dramatic shadows", "Backlit",
                "Candlelight", "Overcast natural light"
            ])
        with col2:
            st.session_state.img_colors = st.selectbox("Colour palette:", [
                "Vibrant", "Muted / pastel", "Monochrome", "Warm tones",
                "Cool tones", "High contrast", "Earth tones", "Neon"
            ])
            st.session_state.img_composition = st.selectbox("Composition:", [
                "Close-up portrait", "Wide establishing shot", "Rule of thirds",
                "Symmetrical", "Bird's eye view", "Low angle", "Panoramic",
                "Dutch angle", "Over-the-shoulder"
            ])
            st.session_state.img_extra = st.text_input(
                "Extra details (optional):",
                placeholder="e.g. Inspired by Blade Runner, hyper-detailed, 4K"
            )
            if tool["supports_negative"]:
                st.session_state.img_negative = st.text_input(
                    "Things to avoid:",
                    placeholder="e.g. blurry, distorted faces, watermark"
                )

        if st.button("✨ Generate Image Prompt", type="primary") and st.session_state.img_subject.strip():
            negative_note = (
                f"\nThings to exclude: {st.session_state.img_negative}"
                if tool["supports_negative"] and st.session_state.img_negative else ""
            )
            user_msg = f"""Generate a high-performing {st.session_state.img_tool} image prompt for:

Subject/scene: {st.session_state.img_subject}
Art style: {st.session_state.img_art_style}
Mood/atmosphere: {st.session_state.img_mood}
Lighting: {st.session_state.img_lighting}
Colour palette: {st.session_state.img_colors}
Composition: {st.session_state.img_composition}
Extra details: {st.session_state.img_extra or 'none'}{negative_note}

Output ONLY the final ready-to-use prompt. No explanation. No preamble."""

            with st.spinner(f"Crafting your {st.session_state.img_tool} prompt…"):
                st.session_state.img_generated = call_model(tool["system"], user_msg)
                st.session_state.img_rating = ""
                st.session_state.img_step = 2
            st.rerun()

    elif st.session_state.img_step == 2:
        st.markdown(f"**✅ Your {st.session_state.img_tool} prompt**")
        st.text_area("", value=st.session_state.img_generated, height=200)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button("📥 Download", data=st.session_state.img_generated,
                               file_name="image_prompt.txt", mime="text/plain")
        with col2:
            if st.button("⭐ Rate This Prompt"):
                tool_name = st.session_state.img_tool
                with st.spinner("Rating…"):
                    st.session_state.img_rating = call_model(
                        system=f"""You are an expert {tool_name} prompt engineer and quality reviewer.
You give concise, specific, actionable feedback. You focus on what will actually improve results,
not generic advice. You score honestly — a 10 is rare.""",
                        user=f"""Rate this {tool_name} prompt:

{st.session_state.img_generated}

Original intent: {st.session_state.img_subject}

Provide exactly:
1. Score: X/10
2. Strengths (2-3 bullet points — be specific)
3. Weaknesses (2-3 bullet points — be specific)
4. Improved version: [rewrite the weakest part of the prompt]"""
                    )
                st.rerun()
        with col3:
            if st.button("🔄 Start Again"):
                st.session_state.img_step = 1
                st.session_state.img_generated = ""
                st.session_state.img_rating = ""
                st.rerun()

        if st.session_state.img_rating:
            st.markdown('<div class="rating-box">', unsafe_allow_html=True)
            st.markdown("**⭐ Prompt Rating**")
            st.markdown(st.session_state.img_rating)
            st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TEXT PROMPT MODE
# ══════════════════════════════════════════════════════════════════════════════
else:
    # ── Prompt history ────────────────────────────────────────────────────────
    if st.session_state.history:
        if st.button("📚 View Prompt History"):
            st.session_state.show_history = not st.session_state.show_history

    if st.session_state.show_history and st.session_state.history:
        st.markdown("### 📖 Prompt History")
        for i, p in enumerate(st.session_state.history):
            st.markdown(f"**Prompt {i+1}:** {p[:100]}{'...' if len(p) > 100 else ''}")
            with st.expander("View Full Prompt"):
                st.code(p)

        if st.button("📄 Download All as PDF"):
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
                buffer.write(pdf.output(dest='S').encode('latin1'))
                buffer.seek(0)
                st.download_button("📥 Download PDF", data=buffer,
                                   file_name="prompts.pdf", mime="application/pdf")

    # ── Step 1 ────────────────────────────────────────────────────────────────
    if st.session_state.step == 1:
        st.markdown("### Step 1: What do you want to achieve?")
        st.session_state.goal = st.text_area(
            "Describe your task:",
            placeholder="e.g. I need an AI to help me write a weekly email newsletter for my B2B SaaS company"
        )
        st.session_state.style = st.selectbox(
            "Prompt style:",
            ["Creative", "Technical", "Conversational", "Concise", "Formal", "Friendly"]
        )

        if st.button("Continue →", type="primary") and st.session_state.goal.strip():
            with st.spinner("Analysing your task…"):
                questions_raw = call_model(
                    system="""You are a senior prompt engineer who builds prompts for advanced reasoning AI models (o3, Claude Sonnet, Gemini 2.0).
Your job is to identify the key missing information that will make or break the final prompt's quality.
You ask only questions whose answers will genuinely change the prompt — not generic filler questions.
You think about: audience, constraints, tone, output format, edge cases, and context the AI will need.""",
                    user=f"""A user wants to build an AI prompt for this task:
{st.session_state.goal}

Preferred style: {st.session_state.style}

Identify the 3-5 most important clarifying questions that, if answered, would significantly improve the final prompt.
Focus on specifics that a reasoning model would need to avoid ambiguity or making wrong assumptions.

If the goal is already fully specified and unambiguous, return exactly: NONE

Return only the questions, one per line, no numbering, no preamble."""
                )
                content = questions_raw.strip()
                if content.upper() == "NONE":
                    st.session_state.step = 3
                else:
                    st.session_state.questions = [q for q in content.split("\n") if q.strip()]
                    st.session_state.step = 2
            st.rerun()

    # ── Step 2 ────────────────────────────────────────────────────────────────
    elif st.session_state.step == 2:
        st.markdown("### Step 2: A few quick details")
        st.caption("These help build a much stronger prompt. Skip anything that doesn't apply.")
        answer_all = st.checkbox("Let AI fill in all answers")

        with st.form("followups"):
            for q in st.session_state.questions:
                col1, col2 = st.columns([5, 1])
                with col1:
                    val = "Let AI choose" if answer_all else ""
                    answer = st.text_input(q, value=val)
                    st.session_state.answers[q] = answer
                with col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.checkbox("AI", key=f"ai_{q}", help="Let AI decide this"):
                        st.session_state.answers[q] = "Let AI choose"
            if st.form_submit_button("Generate Prompt ✨"):
                st.session_state.step = 3
                st.rerun()

    # ── Step 3 ────────────────────────────────────────────────────────────────
    elif st.session_state.step == 3:
        st.markdown("### Step 3: Your prompt")

        if not st.session_state.generated_prompt:
            with st.spinner("Crafting your prompt…"):
                answers_text = "\n".join(
                    f"- {q}: {a}" for q, a in st.session_state.answers.items()
                ) or "No additional details provided."

                st.session_state.generated_prompt = call_model(
                    system="""You are a world-class prompt engineer who builds prompts specifically designed for advanced reasoning AI models (such as o3, Claude Sonnet 4, Gemini 2.0 Flash).

You know that reasoning models perform best when prompts:
1. Open with a clear, specific role and expertise level ("You are a senior [X] with 15 years of experience in [Y]")
2. Provide rich context — the AI should know WHY it's doing this, not just what
3. State explicit constraints and non-negotiables
4. Specify the exact output format, length, and structure required
5. Include quality criteria — what does "good" look like for this task?
6. Handle edge cases upfront rather than leaving them to chance
7. Avoid vague instructions like "be helpful" or "do your best" — be precise

Your prompts are structured with clear sections using markdown headers where appropriate.
You write prompts that are self-contained — the AI reading the prompt needs zero additional context.
For any user answers marked 'Let AI choose', you supply the best possible default based on the task.""",
                    user=f"""Build a high-quality prompt for this task:

Goal: {st.session_state.goal}
Preferred style: {st.session_state.style}

User's answers to clarifying questions:
{answers_text}

Produce the final prompt only. No commentary, no preamble, no "here is your prompt:".
The output should be ready to paste directly into an AI tool and produce excellent results immediately."""
                )
                st.session_state.history.append(st.session_state.generated_prompt)
                st.session_state.prompt_rating = ""

        st.text_area("Your prompt:", value=st.session_state.generated_prompt, height=350)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button("📥 Download", data=st.session_state.generated_prompt,
                               file_name="prompt.txt", mime="text/plain")
        with col2:
            if st.button("⭐ Rate This Prompt"):
                with st.spinner("Reviewing…"):
                    st.session_state.prompt_rating = call_model(
                        system="""You are a senior prompt engineer who reviews prompts intended for advanced reasoning AI models.
You give specific, honest, actionable feedback. You know what separates a 7/10 prompt from a 9/10 prompt.
You focus on structural completeness, ambiguity, missing context, and output format clarity.
You score honestly — a 10 is exceptionally rare.""",
                        user=f"""Review this AI prompt:

---
{st.session_state.generated_prompt}
---

Original task: {st.session_state.goal}
Style requested: {st.session_state.style}

Provide:
1. Score: X/10
2. What makes this prompt strong (2-3 specific points)
3. What's missing or could cause the AI to go wrong (2-3 specific points)
4. One concrete improvement: rewrite the weakest section of the prompt

Be direct and specific. No generic advice."""
                    )
                st.rerun()
        with col3:
            if st.button("➕ Start Over"):
                for k in ["step", "goal", "questions", "answers",
                          "generated_prompt", "prompt_rating"]:
                    st.session_state[k] = defaults[k]
                st.rerun()

        st.caption("Tip: Ctrl+A then Ctrl+C to select and copy the full prompt.")

        if st.session_state.prompt_rating:
            st.markdown('<div class="rating-box">', unsafe_allow_html=True)
            st.markdown("**⭐ Prompt Review**")
            st.markdown(st.session_state.prompt_rating)
            st.markdown('</div>', unsafe_allow_html=True)


# ─── Feedback ─────────────────────────────────────────────────────────────────
st.markdown("---")
if st.button("💬 Send Feedback"):
    st.session_state.show_feedback = not st.session_state.get("show_feedback", False)

if st.session_state.get("show_feedback", False):
    st.markdown("### 💬 Feedback")
    with st.form("feedback_form"):
        name = st.text_input("Your name (optional)")
        email = st.text_input("Your email (optional)")
        message = st.text_area("Your message")
        if st.form_submit_button("Send Feedback"):
            if not message.strip():
                st.warning("Please enter a message before submitting.")
            else:
                resp = requests.post(
                    "https://formspree.io/f/mgvalkbb",
                    data={"name": name, "email": email, "message": message}
                )
                if resp.status_code == 200:
                    st.success("Thanks for your feedback! ✅")
                else:
                    st.error("Something went wrong. Please try again later.")
