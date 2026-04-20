 ## Symposium.ai
 
 A tiny “arena” that lets **GPT (OpenAI)**, **Claude (Anthropic)**, and **Gemini (Google)** debate a question (propose → critique → revise) until an **arbiter** decides they’ve converged, or we hit a max-round stop condition.
 
 ### What’s implemented
 
 - **Logistics / provider wiring**
   - Loads keys from `.env`
   - Provider adapters:
     - OpenAI → `OPENAI_API_KEY`
     - Anthropic → `ANTHROPIC_API_KEY`
     - Google Gemini → `GOOGLE_API_KEY`
 - **Arena loop**
   - **Start**: each agent produces an initial proposal
   - **Continue**: for each round → each agent critiques others → each agent revises
   - **Stop**: arbiter returns strict JSON `{ agree, final_answer, reason }`
     - If `agree=true`: stop and output `final_answer`
     - Else: continue until `max_rounds`, then produce a synthesis
 
 ### Setup
 
 ```bash
 cd /Users/nithishaddepalli/Documents/cv-fire
 python -m venv .venv
 source .venv/bin/activate
 pip install -U pip
 pip install -e .
 cp .env.example .env
 ```
 
 Edit `.env` and add your API keys.
 
 ### Quick connectivity checks
 
 ```bash
 arena ping --provider gpt
 arena ping --provider claude
 arena ping --provider gemini
 ```
 
 ### Run the arena
 
 3 agents (default):
 
 ```bash
 arena run "Should we use JWTs or server sessions for a B2B SaaS?" --max-rounds 3 --show-transcript
 ```
 
 2 agents:
 
 ```bash
 arena run "Pick a DB migration strategy for 100M rows" --agents 2 --max-rounds 3
 ```
 
 Save a transcript:
 
 ```bash
 arena run "Design an API rate limit policy" --out runs/last.json
 ```
