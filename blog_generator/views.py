import json
import os
import re
import logging
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.contrib import messages
import assemblyai as aai
import yt_dlp
import google.generativeai as genai
from .models import BlogPost

# Configure logging
logger = logging.getLogger(__name__)

# Configure Gemini API
genai.configure(api_key=settings.GEMINI_API_KEY)

# Configure AssemblyAI (should be moved to settings)
aai.settings.api_key = getattr(settings, 'ASSEMBLYAI_API_KEY', '221bcc576eb741e1b5695c4d1c25001b')


@login_required
def index(request):
    """Homepage view for authenticated users."""
    return render(request, 'index.html')


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def generate_blog(request):
    """Generate blog post from YouTube video."""
    try:
        # Parse JSON data
        data = json.loads(request.body)
        yt_link = data.get('link', '').strip()
        
        if not yt_link:
            return JsonResponse({'error': 'YouTube link is required.'}, status=400)
        
        # Validate YouTube URL
        if not is_valid_youtube_url(yt_link):
            return JsonResponse({'error': 'Invalid YouTube URL.'}, status=400)
        
        # Check if blog already exists for this video
        existing_blog = BlogPost.objects.filter(
            user=request.user, 
            youtube_link=yt_link
        ).first()
        
        if existing_blog:
            return JsonResponse({
                'title': existing_blog.youtube_title,
                'content': existing_blog.content,
                'message': 'Blog already exists for this video.'
            }, status=200)
        
        # Get video title
        title = get_youtube_title(yt_link)
        if not title:
            return JsonResponse({'error': 'Could not retrieve video title.'}, status=500)
        
        # Get transcript
        transcription = get_transcript(yt_link)
        if not transcription:
            return JsonResponse({'error': 'Could not retrieve transcript.'}, status=500)
        
        # Generate blog content
        blog_content = generate_blog_content(transcription, title)
        if not blog_content:
            return JsonResponse({'error': 'Could not generate blog content.'}, status=500)
        
        # Save blog article to database
        new_blog_article = BlogPost.objects.create(
            user=request.user,
            youtube_title=title,
            youtube_link=yt_link,
            content=blog_content
        )
        
        logger.info(f"Blog created successfully for user {request.user.username}, video: {title}")
        
        return JsonResponse({
            'title': title, 
            'content': blog_content,
            'blog_id': new_blog_article.pk
        }, status=200)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data.'}, status=400)
    except Exception as e:
        logger.error(f"Error generating blog: {str(e)}")
        return JsonResponse({'error': 'An unexpected error occurred.'}, status=500)


def is_valid_youtube_url(url):
    """Validate YouTube URL format."""
    youtube_patterns = [
        r'^https?://(www\.)?youtube\.com/watch\?v=[\w-]+',
        r'^https?://(www\.)?youtu\.be/[\w-]+',
        r'^https?://(www\.)?youtube\.com/embed/[\w-]+',
        r'^https?://m\.youtube\.com/watch\?v=[\w-]+'
    ]
    return any(re.match(pattern, url) for pattern in youtube_patterns)


def get_youtube_title(yt_link):
    """Extract YouTube video title."""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(yt_link, download=False)
            return info_dict.get('title', 'Unknown Title')
    except Exception as e:
        logger.error(f"Error extracting YouTube title: {str(e)}")
        return None


def sanitize_filename(title):
    """Sanitize filename for safe file system storage."""
    # Remove/replace dangerous characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', title)
    # Limit length and remove leading/trailing dots and spaces
    sanitized = sanitized[:100].strip('. ')
    return sanitized if sanitized else 'untitled'


def download_audio(link):
    """Download audio from YouTube video."""
    try:
        # First, get video info to create filename
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            title = sanitize_filename(info_dict.get('title', 'unknown'))
        
        # Ensure media directory exists
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        
        output_path = os.path.join(settings.MEDIA_ROOT, f"{title}.mp3")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(settings.MEDIA_ROOT, f'{title}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        
        # Add ffmpeg location if specified in settings
        if hasattr(settings, 'FFMPEG_PATH'):
            ydl_opts['ffmpeg_location'] = settings.FFMPEG_PATH
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])
        
        return output_path
        
    except Exception as e:
        logger.error(f"Error downloading audio: {str(e)}")
        return None


def get_transcript(link):
    """Get transcript from YouTube video."""
    try:
        audio_file = download_audio(link)
        if not audio_file or not os.path.exists(audio_file):
            return None
        
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_file)
        
        # Clean up audio file after transcription
        try:
            os.remove(audio_file)
        except OSError:
            logger.warning(f"Could not remove audio file: {audio_file}")
        
        if transcript.status == aai.TranscriptStatus.error:
            logger.error(f"Transcription failed: {transcript.error}")
            return None
        
        return transcript.text
        
    except Exception as e:
        logger.error(f"Error getting transcript: {str(e)}")
        return None


def generate_blog_content(transcription, title):
    """Generate blog content using Gemini AI."""
    try:
        prompt = f"""
        Create a well-structured blog post based on the following YouTube video transcript.
        
        Video Title: {title}
        
        Instructions:
        - Write an engaging introduction
        - Create clear sections with headings
        - Include key insights and takeaways
        - Write a compelling conclusion
        - Use proper markdown formatting
        - Keep the tone professional but accessible
        
        Transcript:
        {transcription}
        
        Blog Post:
        """
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        
        return response.text
        
    except Exception as e:
        logger.error(f"Error generating blog content: {str(e)}")
        return None


@require_http_methods(["GET", "POST"])
def user_signup(request):
    """Handle user registration."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        repeatpassword = request.POST.get('repeatpassword', '')
        
        # Validation
        if not all([username, email, password, repeatpassword]):
            messages.error(request, 'All fields are required.')
            return render(request, 'signup.html')
        
        if password != repeatpassword:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'signup.html')
        
        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, 'signup.html')
        
        # Check if user already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
            return render(request, 'signup.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered.')
            return render(request, 'signup.html')
        
        try:
            user = User.objects.create_user(username=username, email=email, password=password)
            login(request, user)
            messages.success(request, 'Account created successfully!')
            return redirect('index')
        except ValidationError as e:
            messages.error(request, f'Registration failed: {e.message}')
        except Exception as e:
            logger.error(f"Signup error: {str(e)}")
            messages.error(request, 'An error occurred during registration.')
    
    return render(request, 'signup.html')


@login_required
def blog_list(request):
    """Display user's blog posts."""
    blogs = BlogPost.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'all-blogs.html', {'blogs': blogs})


@login_required
def blog_details(request, pk):
    """Display individual blog post."""
    blog = get_object_or_404(BlogPost, pk=pk)
    
    # Ensure user can only access their own blogs
    if blog.user != request.user:
        messages.error(request, 'You do not have permission to view this blog.')
        return redirect('blog_list')
    
    return render(request, 'blog-details.html', {'blog': blog})


@require_http_methods(["GET", "POST"])
def user_login(request):
    """Handle user authentication."""
    if request.method == 'POST':
        # Support both username and email login
        username_or_email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        if not username_or_email or not password:
            messages.error(request, 'Both email and password are required.')
            return render(request, 'login.html')
        
        # Try to authenticate with email first, then username
        user = None
        if '@' in username_or_email:
            # Email login
            try:
                user_obj = User.objects.get(email=username_or_email)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass
        else:
            # Username login
            user = authenticate(request, username=username_or_email, password=password)
        
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', 'index')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid credentials.')
    
    return render(request, 'login.html')


@login_required
def user_logout(request):
    """Handle user logout."""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('user_login')