import json
from os import link
import os
import re
from django.conf import settings
from django.shortcuts import render , redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import assemblyai as aai
import yt_dlp
import google.generativeai as genai
from .models import BlogPost

genai.configure(api_key=settings.GEMINI_API_KEY)

#client = OpenAI()

# Create your views here.
@login_required
def index(request):
  return render(request, 'index.html')


@csrf_exempt
def generate_blog(request):
  if request.method == 'POST':
    try:
      data = json.loads(request.body)
      yt_link = data['link']
    except (KeyError, json.JSONDecodeError):
      return JsonResponse({'error': 'Invalid data.'}, status=400)
    
    
    #get title
    title = yt_title(yt_link)
    #get transcript
    transcription = get_transcript(yt_link)
    if not transcription:
      return JsonResponse({'error': 'Could not retrieve transcript.'}, status=500)
    #use openai to generate blog
    blog_content = generate_blog_content(transcription)
    if not blog_content:
      return JsonResponse({'error': 'Could not generate blog content.'}, status=500)
    #save blog article to db
    new_blog_article = BlogPost.objects.create(
      user=request.user,
      youtube_title=title,
      youtube_link=yt_link,
      content=blog_content
    )

    new_blog_article.save()
    #return blog article as a response
    return JsonResponse({'title': title, 'content': blog_content}, status=200)

  
  else:
    return JsonResponse({'error': 'Invalid request method.'}, status=400)


def yt_title(yt_link):
    ydl_opts = {}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(yt_link, download=False)
        return info_dict.get('title', 'Unknown Title')
    

import os
import re
import yt_dlp
import assemblyai as aai
from django.conf import settings


def sanitize_filename(title):
    # Replace any non-alphanumeric character with underscore
    return re.sub(r'[^a-zA-Z0-9_-]', '_', title)


def download_audio(link):
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        info_dict = ydl.extract_info(link, download=False)
        title = sanitize_filename(info_dict['title'])

    # Ensure file is written with a safe filename
    ydl_opts = {
        'format': 'bestaudio/best',
        "cookies": "cookies.txt",  # path to exported cookies
        'outtmpl': os.path.join(settings.MEDIA_ROOT, f'{title}.%(ext)s'),
        'ffmpeg_location': '/opt/homebrew/bin/ffmpeg',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([link])

    return os.path.join(settings.MEDIA_ROOT, f"{title}.mp3")


def get_transcript(link):
    audio_file = download_audio(link)
    aai.settings.api_key = "221bcc576eb741e1b5695c4d1c25001b"  # better load from .env
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_file)
    return transcript.text


def generate_blog_content(transcription):
    prompt = f"Generate a blog post based on the following transcript:\n\n{transcription}\n\nArticle:"

    # Initialize the model (choose gemini-1.5-pro or gemini-1.5-flash)
    model = genai.GenerativeModel("gemini-1.5-flash")

    # Generate content
    response = model.generate_content(prompt)

    # The text output
    generated_content = response.text  

    return generated_content


def user_signup(request):
  if request.method == 'POST':
    # Handle signup logic here
    username = request.POST.get('username')
    email = request.POST.get('email')
    password = request.POST.get('password')
    repeatpassword = request.POST.get('repeatpassword')

    if password == repeatpassword:
      try:
        user = User.objects.create_user(username, email, password)
        user.save()
        login(request, user)
        return redirect('index')
      except:
        error_message = "An error occurred during signup."
    else:
      error_message = 'Passwords do not match.'

    return render(request, 'signup.html', {'error_message': error_message})

  return render(request, 'signup.html')

def blog_list(request):
  blogs = BlogPost.objects.filter(user=request.user).order_by('-created_at')
  return render(request, 'all-blogs.html', {'blogs': blogs})

def blog_details(request, pk):
    blog = BlogPost.objects.get(pk=pk)
    if blog.user == request.user:
      return render(request, 'blog-details.html', {'blog': blog})
    else:
       return redirect('/')

def user_login(request):
  if request.method == 'POST':

    email = request.POST.get('email')
    password = request.POST.get('password')

    user = authenticate(request, email=email, password=password)
    if user is not None:
      login(request, user)
      return redirect('/')
    else:
      error_message = "Invalid email or password."
      return render(request, 'login.html', {'error_message': error_message})

  return render(request, 'login.html')


def user_logout(request):
  logout(request)
  return redirect('login')
