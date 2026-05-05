import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
import os
import json
from datetime import datetime
from io import BytesIO
from fpdf import FPDF
import base64
import requests

# Load environment variables
load_dotenv()

# Internal model — do not expose to users
_MODEL = "gpt-4.1"

# Usage limits
FREE_LIMIT = 10
CREDITS_PER_PAYMENT = 50

def _secret(key: str, default: str = "") -> str:
    """Read from Streamlit secrets first, fall back to env vars (local dev)."""
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)

# Vercel KV (Upstash Redis) — used in production
KV_URL   = _secret("KV_REST_API_URL")
KV_TOKEN = _secret("KV_REST_API_TOKEN")
KV_CONFIGURED = bool(KV_URL and KV_TOKEN)

# Stripe Payment Link
PAYMENT_LINK = _secret("PROMPTBUILDER_PAYMENT_LINK")

# OpenAI client — reads OPENAI_API_KEY from secrets or env
client = OpenAI(api_key=_secret("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"))

# Local fallback (dev only — not used in production)
USAGE_FILE = "usage.json"

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
    .usage-bar {{
        background-color: #f8f8f8;
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        padding: 0.5rem 0.75rem;
        margin-bottom: 1rem;
        font-size: 13px;
        color: #555;
    }}
    .usage-bar.warning {{
        background-color: #fff8e1;
        border-color: #f9a825;
        color: #7a5c00;
    }}
    .upgrade-box {{
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        border-radius: 6px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        text-align: center;
    }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="header-container">
  <img src="{logo_data}" class="logo">
  <h1 class="main-title">Interactive Prompt Builder</h1>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# USAGE TRACKING — Vercel KV in production, JSON file for local dev
# ══════════════════════════════════════════════════════════════════════════════

def _kv(command: list):
    """Execute a single Redis command via Upstash REST API."""
    try:
        resp = requests.post(
            KV_URL,
            headers={"Authorization": f"Bearer {KV_TOKEN}"},
            json=command,
            timeout=5
        )
        return resp.json().get("result")
    except Exception:
        return None

def _monthly_key(email: str) -> str:
    month = datetime.now().strftime("%Y-%m")
    return f"promptbuilder:usage:{email.lower().strip()}:{month}"

def _credits_key(email: str) -> str:
    return f"promptbuilder:credits:{email.lower().strip()}"

# ── KV versions ───────────────────────────────────────────────────────────────
def kv_get_usage(email: str) -> int:
    val = _kv(["GET", _monthly_key(email)])
    return int(val) if val else 0

def kv_get_credits(email: str) -> int:
    val = _kv(["GET", _credits_key(email)])
    return max(int(val), 0) if val else 0

def kv_increment_usage(email: str):
    _kv(["INCR", _monthly_key(email)])
    _kv(["EXPIRE", _monthly_key(email), 5184000])  # 60-day TTL

def kv_decrement_credits(email: str):
    _kv(["DECRBY", _credits_key(email), 1])

# ── JSON fallback (local dev only) ────────────────────────────────────────────
def _load_json():
    if os.path.isfile(USAGE_FILE):
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    return {}

def _save_json(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)

def json_get_usage(email: str) -> int:
    month = datetime.now().strftime("%Y-%m")
    return _load_json().get(f"{email.lower().strip()}::{month}", 0)

def json_get_credits(email: str) -> int:
    return _load_json().get(f"{email.lower().strip()}::credits", 0)

def json_increment_usage(email: str):
    data = _load_json()
    month = datetime.now().strftime("%Y-%m")
    key = f"{email.lower().strip()}::{month}"
    data[key] = data.get(key, 0) + 1
    _save_json(data)

def json_decrement_credits(email: str):
    data = _load_json()
    key = f"{email.lower().strip()}::credits"
    data[key] = max(data.get(key, 0) - 1, 0)
    _save_json(data)

# ── Unified interface ─────────────────────────────────────────────────────────
def get_usage(email: str) -> int:
    return kv_get_usage(email) if KV_CONFIGURED else json_get_usage(email)

def get_credits(email: str) -> int:
    return kv_get_credits(email) if KV_CONFIGURED else json_get_credits(email)

def do_increment_usage(email: str):
    kv_increment_usage(email) if KV_CONFIGURED else json_increment_usage(email)

def do_decrement_credits(email: str):
    kv_decrement_credits(email) if KV_CONFIGURED else json_decrement_credits(email)


# ─── Email gate ───────────────────────────────────────────────────────────────
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

if not st.session_state.user_email:
    st.markdown("### Welcome to the Prompt Builder")
    st.markdown(
        "Enter your email to get started. You get **10 free requests per month** — "
        "no payment required."
    )
    with st.form("email_gate"):
        email_input = st.text_input("Your email address:")
        if st.form_submit_button("Get Started →", type="primary"):
            val = email_input.strip()
            if "@" in val and "." in val:
                st.session_state.user_email = val.lower()
                st.rerun()
            else:
                st.warning("Please enter a valid email address.")
    st.stop()

# Allow email reset via query param
if st.query_params.get("reset_email") == "1":
    st.session_state.user_email = ""
    st.query_params.clear()
    st.rerun()

# ─── Usage display ────────────────────────────────────────────────────────────
_email       = st.session_state.user_email
_usage       = get_usage(_email)
_credits     = get_credits(_email)
_free_left   = max(0, FREE_LIMIT - _usage)
_has_credits = _credits > 0
_at_limit    = _free_left == 0 and not _has_credits
_warn        = _free_left <= 3 and not _has_credits

_usage_class = "usage-bar warning" if _warn else "usage-bar"
_usage_icon  = "⚠️" if _warn else "🔢"

if _has_credits:
    _usage_text = (
        f"{_usage_icon} <strong>{_free_left}</strong> free requests left this month "
        f"· <strong>{_credits}</strong> paid credits "
        f"&nbsp;·&nbsp; <small>{_email}</small> "
        f'<a href="?reset_email=1" style="float:right;font-size:11px;color:#aaa;">change email</a>'
    )
else:
    _usage_text = (
        f"{_usage_icon} <strong>{_free_left}</strong> of {FREE_LIMIT} free requests remaining this month "
        f"&nbsp;·&nbsp; <small>{_email}</small> "
        f'<a href="?reset_email=1" style="float:right;font-size:11px;color:#aaa;">change email</a>'
    )

st.markdown(f'<div class="{_usage_class}">{_usage_text}</div>', unsafe_allow_html=True)

# ─── Upgrade banner (shown when limit is hit) ─────────────────────────────────
if _at_limit:
    upgrade_url = f"{PAYMENT_LINK}?prefilled_email={_email}" if PAYMENT_LINK else "#"
    st.markdown(
        f'<div class="upgrade-box">'
        f"<strong>You've used all your free requests for this month.</strong><br>"
        f"Get <strong>{CREDITS_PER_PAYMENT} more requests</strong> to keep going.<br><br>"
        f'<a href="{upgrade_url}" target="_blank" style="background:#4361ee;color:white;'
        f'padding:0.5rem 1.5rem;border-radius:4px;text-decoration:none;font-weight:600;">'
        f"Get more requests →</a>"
        f"</div>",
        unsafe_allow_html=True
    )
    st.stop()


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
    "Image Gen 2 (Open AI)": {
        "description": "Rich natural language — narrative and descriptive",
        "supports_negative": False,
        "system": """You are an Image Gen 2 (OpenAI) expert. Image Gen 2 is trained on natural language and rewards:
- Clear, vivid narrative descriptions written as complete, flowing sentences
- Explicit specification of composition, perspective, and framing
- Detailed lighting and atmosphere description
- Style references (e.g. "in the style of a 1970s National Geographic photograph")
- Specific mention of what should NOT dominate the image (weave exclusions into the description rather than using negative prompts)

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

# ─── Video tool definitions ───────────────────────────────────────────────────
VIDEO_TOOLS = {
    "Sora (OpenAI)": {
        "description": "Cinematic prose — describe the scene and how it unfolds over time",
        "system": """You are a Sora expert prompt writer. Sora generates video from natural language and rewards:
- Cinematic prose written as flowing, descriptive sentences (not bullet points)
- Temporal progression: describe what changes or happens over the duration, not just a static scene
- Camera language woven naturally into the description: "the camera slowly drifts back to reveal...", "a tight close-up shows..."
- Specific motion details: how subjects move, how light changes, how the environment shifts
- Atmosphere and mood set through sensory language
- Aim for 3–6 sentences that tell a complete visual story with a beginning, middle, and end

Do NOT use technical parameter syntax. Write as if directing a short film.""",
    },
    "Runway Gen-3": {
        "description": "Structured directives — camera type, action, environment, mood",
        "system": """You are a Runway Gen-3 expert. Runway responds best to:
- Opening with the camera setup and shot type: "Medium close-up shot:", "Wide establishing shot:"
- Explicit camera motion cues: "slow dolly forward", "gentle pan right", "static locked-off"
- Subject and action described in present tense, clearly separated from environment
- Scene and environment details following the subject description
- Lighting and time-of-day specification
- Closing with mood and atmosphere

Format each prompt as:
[Shot type], [subject and action], [environment and setting], [camera movement], [lighting], [mood/atmosphere]

Keep it concise — Runway performs best with focused, unambiguous directives.""",
    },
    "Kling": {
        "description": "Motion-first descriptions — lead with action and movement",
        "system": """You are a Kling video generation expert. Kling excels when prompts:
- Lead immediately with the primary subject and their specific motion or action
- Follow with environment and atmospheric detail
- Specify camera perspective and any camera movement clearly
- Use temporal language to describe motion quality: "gradually", "suddenly", "smoothly", "in slow motion"
- Reference a cinematic style or film genre for visual consistency
- Stay focused on one clear central action — competing elements reduce quality

Write a single descriptive paragraph, 3–5 sentences. Prioritise motion clarity above all else.
Avoid vague words like "beautiful" or "amazing" — be specific about what the viewer actually sees.""",
    },
}

# ─── Session state defaults ───────────────────────────────────────────────────
defaults = {
    # Text prompt
    "step": 1, "goal": "", "style": "",
    "questions": [], "answers": {},
    "generated_prompt": "", "prompt_rating": "",
    "history": [], "show_history": False, "show_feedback": False,
    # Image prompt
    "img_step": 1, "img_tool": "Midjourney",
    "img_subject": "", "img_art_style": "", "img_mood": "",
    "img_lighting": "", "img_colors": "", "img_composition": "",
    "img_extra": "", "img_negative": "",
    "img_generated": "", "img_rating": "",
    # Video prompt
    "vid_step": 1, "vid_tool": "Sora (OpenAI)",
    "vid_subject": "", "vid_shot_type": "", "vid_camera_move": "",
    "vid_duration": "10 seconds", "vid_style": "", "vid_mood": "",
    "vid_lighting": "", "vid_extra": "",
    "vid_generated": "", "vid_rating": "",
    # System prompt
    "sys_step": 1, "sys_role": "", "sys_purpose": "", "sys_tone": "",
    "sys_rules": "", "sys_output_format": "", "sys_example": "",
    "sys_generated": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# HELPER — call model (with usage + credits tracking)
# ══════════════════════════════════════════════════════════════════════════════
def call_model(system: str, user: str) -> str:
    email   = st.session_state.user_email
    usage   = get_usage(email)
    credits = get_credits(email)

    if usage >= FREE_LIMIT and credits <= 0:
        upgrade_url = f"{PAYMENT_LINK}?prefilled_email={email}" if PAYMENT_LINK else "#"
        st.error(
            f"You've used all your free requests for this month. "
            f"[Get {CREDITS_PER_PAYMENT} more requests]({upgrade_url})"
        )
        st.stop()

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ]
    )

    # Charge free tier first, then paid credits
    if usage < FREE_LIMIT:
        do_increment_usage(email)
    else:
        do_decrement_credits(email)

    return response.choices[0].message.content.strip()


# ─── Mode ─────────────────────────────────────────────────────────────────────
mode = st.radio(
    "Mode",
    ["📝 Text Prompt", "🎨 Image Prompt", "🎬 Video Prompt", "⚙️ System Prompt"],
    horizontal=True,
    label_visibility="collapsed"
)


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
# VIDEO PROMPT MODE
# ══════════════════════════════════════════════════════════════════════════════
elif mode == "🎬 Video Prompt":
    st.markdown("#### 🎬 Video Prompt Builder")
    st.caption("Generates prompts optimised for AI video generation tools.")

    if st.session_state.vid_step == 1:
        st.markdown("**Step 1 — Describe your video**")

        st.session_state.vid_tool = st.selectbox("Target tool:", list(VIDEO_TOOLS.keys()))
        vtool = VIDEO_TOOLS[st.session_state.vid_tool]
        st.caption(f"💡 {vtool['description']}")

        st.session_state.vid_subject = st.text_area(
            "Describe the scene or action:",
            placeholder="e.g. A lone astronaut walking across a red desert landscape, dust swirling around their boots"
        )

        col1, col2 = st.columns(2)
        with col1:
            st.session_state.vid_shot_type = st.selectbox("Shot type:", [
                "Wide / establishing shot", "Medium shot", "Close-up",
                "Extreme close-up", "POV / first person", "Aerial / drone",
                "Over-the-shoulder", "Two-shot"
            ])
            st.session_state.vid_camera_move = st.selectbox("Camera movement:", [
                "Static / locked off", "Slow pan left", "Slow pan right",
                "Tilt up", "Tilt down", "Dolly forward", "Dolly back",
                "Tracking shot", "Handheld / slightly shaky",
                "Orbital / arc around subject", "Zoom in", "Zoom out"
            ])
            st.session_state.vid_duration = st.selectbox("Duration:", [
                "5 seconds", "10 seconds", "15 seconds", "20 seconds"
            ])
        with col2:
            st.session_state.vid_style = st.selectbox("Visual style:", [
                "Cinematic / film", "Photorealistic", "Documentary",
                "Slow motion", "Animated / stylised", "Time-lapse",
                "Noir / high contrast", "Dreamy / soft focus"
            ])
            st.session_state.vid_mood = st.selectbox("Mood:", [
                "Dramatic", "Serene", "Mysterious", "Tense", "Joyful",
                "Melancholic", "Epic", "Intimate", "Ominous", "Uplifting"
            ])
            st.session_state.vid_lighting = st.selectbox("Lighting:", [
                "Golden hour / magic hour", "Harsh midday sun", "Overcast / diffused",
                "Night / low light", "Neon / artificial", "Candlelight / fire",
                "Studio / controlled", "Backlit / silhouette"
            ])
            st.session_state.vid_extra = st.text_input(
                "Extra details (optional):",
                placeholder="e.g. Inspired by Dune, ultra-realistic, 4K"
            )

        if st.button("✨ Generate Video Prompt", type="primary") and st.session_state.vid_subject.strip():
            user_msg = f"""Generate a high-performing {st.session_state.vid_tool} video prompt for:

Scene / action: {st.session_state.vid_subject}
Shot type: {st.session_state.vid_shot_type}
Camera movement: {st.session_state.vid_camera_move}
Duration: {st.session_state.vid_duration}
Visual style: {st.session_state.vid_style}
Mood: {st.session_state.vid_mood}
Lighting: {st.session_state.vid_lighting}
Extra details: {st.session_state.vid_extra or 'none'}

Output ONLY the final ready-to-use prompt. No explanation. No preamble."""

            with st.spinner(f"Crafting your {st.session_state.vid_tool} prompt…"):
                st.session_state.vid_generated = call_model(vtool["system"], user_msg)
                st.session_state.vid_rating = ""
                st.session_state.vid_step = 2
            st.rerun()

    elif st.session_state.vid_step == 2:
        st.markdown(f"**✅ Your {st.session_state.vid_tool} prompt**")
        st.text_area("", value=st.session_state.vid_generated, height=200)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button("📥 Download", data=st.session_state.vid_generated,
                               file_name="video_prompt.txt", mime="text/plain")
        with col2:
            if st.button("⭐ Rate This Prompt"):
                tool_name = st.session_state.vid_tool
                with st.spinner("Rating…"):
                    st.session_state.vid_rating = call_model(
                        system=f"""You are an expert {tool_name} prompt engineer and video generation specialist.
You give concise, specific, actionable feedback focused on what will actually improve the video output.
You score honestly — a 10 is rare.""",
                        user=f"""Rate this {tool_name} video prompt:

{st.session_state.vid_generated}

Original intent: {st.session_state.vid_subject}

Provide exactly:
1. Score: X/10
2. Strengths (2-3 bullet points — be specific)
3. Weaknesses (2-3 bullet points — be specific)
4. Improved version: [rewrite the weakest part of the prompt]"""
                    )
                st.rerun()
        with col3:
            if st.button("🔄 Start Again"):
                st.session_state.vid_step = 1
                st.session_state.vid_generated = ""
                st.session_state.vid_rating = ""
                st.rerun()

        if st.session_state.vid_rating:
            st.markdown('<div class="rating-box">', unsafe_allow_html=True)
            st.markdown("**⭐ Prompt Rating**")
            st.markdown(st.session_state.vid_rating)
            st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT MODE
# ══════════════════════════════════════════════════════════════════════════════
elif mode == "⚙️ System Prompt":
    st.markdown("#### ⚙️ System Prompt Builder")
    st.caption("Build a complete system prompt to define how an AI assistant behaves.")

    if st.session_state.sys_step == 1:
        st.markdown("**Describe your AI assistant**")

        st.session_state.sys_role = st.text_input(
            "Role / persona:",
            placeholder="e.g. Senior customer support agent for a B2B SaaS company"
        )
        st.session_state.sys_purpose = st.text_area(
            "Primary task or purpose:",
            placeholder="e.g. Answer customer questions about billing, account issues, and product features. Escalate complex technical issues to the engineering team."
        )

        col1, col2 = st.columns(2)
        with col1:
            st.session_state.sys_tone = st.selectbox("Tone and personality:", [
                "Professional and concise", "Friendly and warm",
                "Formal and authoritative", "Conversational and casual",
                "Empathetic and supportive", "Direct and no-nonsense",
                "Enthusiastic and energetic", "Calm and reassuring"
            ])
            st.session_state.sys_output_format = st.selectbox("Preferred output format:", [
                "Clear prose paragraphs", "Structured with headers",
                "Numbered steps / instructions", "Bullet points",
                "Short and punchy — minimal words", "Detailed and thorough",
                "Markdown formatted", "Plain text only"
            ])
        with col2:
            st.session_state.sys_rules = st.text_area(
                "Key rules and constraints:",
                placeholder="e.g. Never discuss competitor products. Always ask for the customer's account ID before troubleshooting.",
                height=120
            )
            st.session_state.sys_example = st.text_area(
                "Example of ideal output (optional):",
                placeholder="Paste an example of exactly how you want the AI to respond — this is the single most powerful thing you can provide.",
                height=120
            )

        if st.button("⚙️ Build System Prompt", type="primary") and st.session_state.sys_role.strip() and st.session_state.sys_purpose.strip():
            user_msg = f"""Build a complete, production-ready system prompt for an AI assistant with these specifications:

Role / persona: {st.session_state.sys_role}
Primary task: {st.session_state.sys_purpose}
Tone and personality: {st.session_state.sys_tone}
Output format preference: {st.session_state.sys_output_format}
Key rules and constraints: {st.session_state.sys_rules or 'none specified'}
Example of ideal output: {st.session_state.sys_example or 'none provided'}

Output ONLY the final system prompt, ready to paste directly into an AI tool. No explanation. No preamble."""

            with st.spinner("Building your system prompt…"):
                st.session_state.sys_generated = call_model(
                    system="""You are a world-class prompt engineer specialising in system prompts for AI assistants.
You know that the best system prompts:
1. Open with a precise role definition including relevant expertise and context
2. State the primary purpose and scope clearly — what the AI does AND does not do
3. Define tone, personality, and communication style with concrete guidance
4. List hard rules and constraints explicitly, in order of importance
5. Specify output format with enough detail that there is no ambiguity
6. Handle edge cases and failure modes upfront
7. Are written directly to the AI ("You are...", "You must...", "When asked about X, always...")
8. Are self-contained — the AI reading this needs zero additional context

You write prompts that are tight, specific, and leave nothing to chance.
You avoid vague instructions like "be helpful" and replace them with precise behavioural directives.""",
                    user=user_msg
                )
                st.session_state.sys_step = 2
            st.rerun()

    elif st.session_state.sys_step == 2:
        st.markdown("**✅ Your system prompt**")
        st.text_area("", value=st.session_state.sys_generated, height=350)
        st.caption("Tip: Ctrl+A then Ctrl+C to select and copy the full prompt.")

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("📥 Download", data=st.session_state.sys_generated,
                               file_name="system_prompt.txt", mime="text/plain")
        with col2:
            if st.button("🔄 Start Again"):
                st.session_state.sys_step = 1
                st.session_state.sys_generated = ""
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TEXT PROMPT MODE
# ══════════════════════════════════════════════════════════════════════════════
elif mode == "📝 Text Prompt":
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
        name    = st.text_input("Your name (optional)")
        email   = st.text_input("Your email (optional)")
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
