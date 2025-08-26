This project is an **AI Blog Generator** that converts YouTube videos into high-quality written blog posts.
It combines multiple technologies to automate the process from video → transcription → content generation:
yt-dlp + ffmpeg → Download and extract YouTube audio
AssemblyAI → Transcribe speech into text
Gemini AI / OpenAI → Generate blog articles from transcripts
Django + PostgreSQL → Backend API and database for managing blog posts
User Authentication → Secure login system to manage generated content

**Features**
🔗 Input a YouTube link
🎧 Audio downloaded and converted to MP3
🗒️ Automatic transcription with AssemblyAI
✍️ AI-generated blog post (Gemini / GPT-based)
👤 User login & blog post management (Django backend)
💾 Store results in PostgreSQL database

⚡ Perfect for content creators, bloggers, or educators who want to quickly repurpose video content into written articles.