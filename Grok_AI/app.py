from dotenv import load_dotenv

# Gemini AI integration from AI.py
def generate_ai_response(prompt, api_key, retries=3, timeout=30):
    """
    Generates a response from the Gemini 2.0 Flash model using the API.
    Retries if the request times out or fails temporarily.
    """
    if not api_key:
        return "Error: Gemini API key is missing."

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {
        'Content-Type': 'application/json',
        'X-goog-api-key': api_key
    }
    data = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=timeout)
            response.raise_for_status()
            json_response = response.json()
            if "candidates" in json_response:
                parts = json_response["candidates"][0].get("content", {}).get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"]
            return "Error: Could not extract text from the API response."
        except requests.exceptions.Timeout:
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            return f"Error: API request failed. Details: {e}"
    return "❌ Failed after multiple attempts due to timeout or network issues."
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import re
from datetime import datetime
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os
from dateutil import parser
import dateutil.relativedelta as rd
from flask_session import Session
import json
from models import db, Reminder, CommandHistory, init_db
from config import Config

import time
from logging_config import setup_logging

app = Flask(__name__)
app.config.from_object(Config)
Session(app)
init_db(app)
logger = setup_logging()

SCOPES = ['https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/gmail.modify']

def create_flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id": app.config['GOOGLE_CLIENT_ID'],
                "client_secret": app.config['GOOGLE_CLIENT_SECRET'],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [url_for('callback', _external=True)]
            }
        },
        scopes=SCOPES
    )

def credentials_to_dict(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

def authenticate_google_calendar():
    try:
        if 'google_credentials' not in session:
            return None
        creds = Credentials.from_authorized_user_info(session['google_credentials'], SCOPES)
        if not creds or not creds.valid:
            return None
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Calendar auth error: {e}")
        return None

def authenticate_gmail():
    try:
        if 'google_credentials' not in session:
            return None
        creds = Credentials.from_authorized_user_info(session['google_credentials'], SCOPES)
        if not creds or not creds.valid:
            return None
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        logger.error(f"Gmail auth error: {e}")
        return None

def create_calendar_event(task, time_phrase):
    try:
        if 'google_credentials' not in session:
            return "🔒 <a href='/login' style='color: #007bff;'>Sign in with Google</a> to enable calendar integration"
        # Parse time_phrase for specific times (e.g., 'at 5 PM')
        from dateutil.parser import parse as dt_parse
        base_time = datetime.now()
        if 'tomorrow' in time_phrase.lower():
            base_time = base_time + rd.relativedelta(days=1)
        try:
            parsed_time = dt_parse(time_phrase, fuzzy=True, default=base_time)
            start_time = parsed_time
        except Exception:
            start_time = base_time + rd.relativedelta(hours=2)  # Fallback
        end_time = start_time + rd.relativedelta(hours=1)
        event = {
            'summary': f"Reminder: {task}",
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'description': f'Created by AI Assistant: {time_phrase}'
        }
        service = authenticate_google_calendar()
        if service:
            event = service.events().insert(calendarId='primary', body=event).execute()
            return f"✅ Calendar event created! <a href='{event.get('htmlLink')}' target='_blank' style='color: #007bff;'>View in Calendar</a>"
        else:
            return "✅ Reminder set! (Re-authentication needed)"
    except Exception as e:
        logger.error(f"Error creating calendar event: {e}")
        return f"✅ Reminder set! (Calendar: {str(e)})"

def parse_reminder_text(text):
    time_patterns = [
        r'at\s+\d{1,2}(:\d{2})?\s*(am|pm|AM|PM)?',
        r'tomorrow',
        r'next\s+\w+',
        r'in\s+\d+\s+(hours|minutes|days)',
        r'\d{1,2}(:\d{2})?\s*(am|pm|AM|PM)',
        r'today',
        r'this\s+\w+',
        r'morning',
        r'afternoon',
        r'evening',
        r'night'
    ]
    time_phrase = None
    for pattern in time_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            time_phrase = match.group(0)
            break
    task = text
    remove_phrases = [
        'remind me to', 'please', 'set a reminder for', 
        'can you', 'could you', 'i need to', 'set a reminder to',
        'remember to', 'don\'t forget to'
    ]
    for phrase in remove_phrases:
        task = re.sub(phrase, '', task, flags=re.IGNORECASE)
    if time_phrase:
        task = task.replace(time_phrase, '')
    task = task.strip()
    task = re.sub(r'^\s*(to|that|about)\s+', '', task)
    task = re.sub(r'\s+', ' ', task).strip()
    if not time_phrase:
        time_phrase = "in 1 hour"
    return task, time_phrase

def get_weather(city="Chennai"):
    try:
        api_key = app.config['WEATHER_API_KEY']
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data['cod'] == 200:
            temp = data['main']['temp']
            description = data['weather'][0]['description']
            humidity = data['main']['humidity']
            wind = data['wind']['speed']
            return f"🌤️ {city.title()}: {temp}°C, {description}, 💧{humidity}% humidity, 💨{wind}m/s wind"
        else:
            return f"❌ Couldn't find weather for {city}. Try another city."
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        return f"⚠️ Weather service unavailable. Error: {str(e)}"

def handle_reminder(user_input):
    try:
        task, time_phrase = parse_reminder_text(user_input)
        user_id = session.get('user_id', 'anonymous')
        new_reminder = Reminder(
            task=task,
            time_phrase=time_phrase,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            completed=False,
            user_id=user_id
        )
        db.session.add(new_reminder)
        db.session.commit()
        calendar_result = create_calendar_event(task, time_phrase)
        response_text = f"""
🎯 **Reminder Created Successfully!**

📋 **Task:** {task}
⏰ **Time:** {time_phrase}
📅 **Status:** {calendar_result}

💡 All reminders are stored in your session
"""
        return {
            'status': 'success',
            'response': response_text,
            'reminders': [{'id': r.id, 'task': r.task, 'time_phrase': r.time_phrase, 'created_at': r.created_at, 'completed': r.completed} for r in Reminder.query.filter_by(user_id=user_id).all()]
        }
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating reminder: {e}")
        return {
            'status': 'error',
            'response': f"❌ Error creating reminder: {str(e)}"
        }

def handle_email(user_input):
    try:
        recipient = None
        subject = None
        if ' to ' in user_input.lower():
            parts = user_input.lower().split(' to ')
            if len(parts) > 1:
                recipient = parts[1].split(' about ')[0].strip()
        if ' about ' in user_input.lower():
            parts = user_input.lower().split(' about ')
            if len(parts) > 1:
                subject = parts[1].strip()
        if 'send' in user_input.lower():
            if recipient and subject:
                return {
                    'status': 'success',
                    'response': f"📧 Ready to send email to {recipient} about {subject}. In full version, this would integrate with Gmail API."
                }
            elif recipient:
                return {
                    'status': 'success',
                    'response': f"📧 Draft created for {recipient}. What's the subject?"
                }
            else:
                return {
                    'status': 'success',
                    'response': "📧 I've prepared an email draft. Ready to send!"
                }
        else:
            return {
                'status': 'success', 
                'response': "📧 I can help with email management. Try 'Send email to professor' or 'Sort my emails'"
            }
    except Exception as e:
        logger.error(f"Email handling error: {e}")
        return {
            'status': 'error',
            'response': f"❌ Email error: {str(e)}"
        }

def handle_email_sorting(user_input):
    try:
        service = authenticate_gmail()
        if not service:
            return {
                'status': 'error',
                'response': "🔒 <a href='/login' style='color: #007bff;'>Sign in with Google</a> to enable email sorting"
            }
        label = None
        if 'important' in user_input.lower():
            label = 'IMPORTANT'
        elif 'work' in user_input.lower():
            label = 'CATEGORY_WORK'
        elif 'personal' in user_input.lower():
            label = 'CATEGORY_PERSONAL'
        else:
            label = 'INBOX'
        query = f"from:me label:{label}"
        results = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = results.get('messages', [])
        if not messages:
            return {
                'status': 'success',
                'response': f"No emails found in {label}."
            }
        response_text = f"📧 Found {len(messages)} emails in {label}:\n"
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
            headers = msg_data['payload']['headers']
            subject = next((header['value'] for header in headers if header['name'] == 'Subject'), 'No Subject')
            response_text += f"- {subject}\n"
        return {
            'status': 'success',
            'response': response_text
        }
    except Exception as e:
        logger.error(f"Email sorting error: {e}")
        return {
            'status': 'error',
            'response': f"❌ Email sorting error: {str(e)}"
        }

def handle_resource_suggestion(user_input):
    try:
        topic = user_input.lower().replace('suggest', '').replace('resources', '').strip()
        if not topic:
            return {
                'status': 'error',
                'response': "Please specify a topic for resource suggestions, e.g., 'Suggest resources for Python programming'"
            }
        resources = {
            'python': [
                {'title': 'Python Official Documentation', 'url': 'https://docs.python.org/3/'},
                {'title': 'Real Python Tutorials', 'url': 'https://realpython.com/'}
            ],
            'productivity': [
                {'title': 'Getting Things Done', 'url': 'https://gettingthingsdone.com/'},
                {'title': 'Todoist', 'url': 'https://todoist.com/'}
            ]
        }
        matched_key = next((key for key in resources if key in topic), None)
        if matched_key:
            response_text = f"📚 Suggested resources for {topic}:\n"
            response_text += '<ul class="resource-list">\n'
            for res in resources[matched_key]:
                response_text += f'<li><a href="{res["url"]}" target="_blank" style="color: #007bff;">{res["title"]}</a></li>\n'
            response_text += '</ul>'
            return {
                'status': 'success',
                'response': response_text
            }
        else:
            return {
                'status': 'success',
                'response': f"No resources found for {topic}. Try another topic!"
            }
    except Exception as e:
        logger.error(f"Resource suggestion error: {e}")
        return {
            'status': 'error',
            'response': f"❌ Resource suggestion error: {str(e)}"
        }

def handle_schedule(user_input):
    try:
        topic = "your meeting"
        if ' about ' in user_input.lower():
            parts = user_input.lower().split(' about ')
            if len(parts) > 1:
                topic = parts[1].strip()
        return {
            'status': 'success',
            'response': f"📅 I've scheduled time for {topic}. In full version, this would sync with Google Calendar."
        }
    except Exception as e:
        logger.error(f"Scheduling error: {e}")
        return {
            'status': 'error',
            'response': f"❌ Scheduling error: {str(e)}"
        }

def handle_weather(user_input):
    try:
        city = "Chennai"
        if " in " in user_input.lower():
            parts = user_input.lower().split(" in ")
            if len(parts) > 1:
                city = parts[1].strip()
        elif " for " in user_input.lower():
            parts = user_input.lower().split(" for ")
            if len(parts) > 1:
                city = parts[1].strip()
        elif " of " in user_input.lower():
            parts = user_input.lower().split(" of ")
            if len(parts) > 1:
                city = parts[1].strip()
        weather_info = get_weather(city)
        return {
            'status': 'success', 
            'response': weather_info
        }
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return {
            'status': 'error',
            'response': f"❌ Weather error: {str(e)}"
        }

def handle_help():
    has_google_auth = 'google_credentials' in session
    if has_google_auth:
        calendar_status = "✅ Google Calendar: Connected"
    else:
        calendar_status = "🔒 Google Calendar: <a href='/login' style='color: #007bff;'>Sign in to enable</a>"
    help_text = f"""
🤖 **AI Personal Assistant**

{calendar_status}

✅ **Working Features:**
**🎯 Reminders** - "Remind me to study at 7 PM"
**🌤️ Weather** - "Weather in Mumbai"
**📧 Email** - "Send email to professor" or "Sort my emails"
**📚 Resources** - "Suggest resources for Python"
**📅 Scheduling** - "Schedule meeting tomorrow"

🚀 **Try these commands:**
- "Remind me to practice demo at 3 PM"
- "What's the weather in Delhi?"
- "Sort my important emails"
- "Suggest resources for productivity"
- "Schedule a meeting for Friday morning"
- "Help"
"""
    return {
        'status': 'success',
        'response': help_text
    }

def handle_command(user_input):
    if not user_input.strip():
        return {
            'status': 'error',
            'response': "Please type a command. Say 'help' to see what I can do!"
        }
    user_id = session.get('user_id', 'anonymous')
    command_history = CommandHistory(
        command=user_input,
        timestamp=datetime.now().strftime("%H:%M:%S"),
        user_id=user_id
    )
    db.session.add(command_history)
    db.session.commit()
    user_input_lower = user_input.lower()
    try:
        if any(word in user_input_lower for word in ['help', 'what can you do', 'commands']):
            return handle_help()
        elif any(word in user_input_lower for word in ['remind', 'remember', 'notify', 'don\'t forget']):
            return handle_reminder(user_input)
        elif any(word in user_input_lower for word in ['email', 'mail', 'gmail']):
            if 'sort' in user_input_lower:
                return handle_email_sorting(user_input)
            return handle_email(user_input)
        elif any(word in user_input_lower for word in ['suggest', 'resources', 'recommend']):
            return handle_resource_suggestion(user_input)
        elif any(word in user_input_lower for word in ['schedule', 'meeting', 'appointment', 'calendar', 'plan']):
            return handle_schedule(user_input)
        elif any(word in user_input_lower for word in ['weather', 'temperature', 'forecast', 'rain', 'sunny']):
            return handle_weather(user_input)
        elif any(word in user_input_lower for word in ['ai', 'gemini', 'chat', 'ask']):
            # AI chat integration (explicit keywords)
            load_dotenv()
            api_key = os.getenv("GEMINI_API_KEY")
            ai_response = generate_ai_response(user_input, api_key)
            return {
                'status': 'success',
                'response': f"🤖 Gemini AI: {ai_response}"
            }
        else:
            # Default to Gemini AI for unmatched input
            load_dotenv()
            api_key = os.getenv("GEMINI_API_KEY")
            ai_response = generate_ai_response(user_input, api_key)
            return {
                'status': 'success',
                'response': f"🤖 Gemini AI: {ai_response}"
            }
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in handle_command: {e}")
        return {
            'status': 'error',
            'response': f"❌ Unexpected error: {str(e)}"
        }

@app.route('/')
def home():
    return render_template('index.html')


# --- Google OAuth 2.0 Login with explicit redirect_uri ---
from google_auth_oauthlib.flow import Flow

@app.route('/login')
def login():
    try:
        flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=[
                'https://www.googleapis.com/auth/calendar.events',
                'https://www.googleapis.com/auth/gmail.modify'
            ],
            redirect_uri='http://localhost:5000/oauth2callback'
        )
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        session['state'] = state
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'status': 'error', 'response': f"Login failed: {str(e)}"})


# --- Google OAuth 2.0 Callback with explicit redirect_uri ---
@app.route('/oauth2callback')
def oauth2callback():
    try:
        state = session.get('state')
        flow = Flow.from_client_secrets_file(
            'credentials.json',
            scopes=[
                'https://www.googleapis.com/auth/calendar.events',
                'https://www.googleapis.com/auth/gmail.modify'
            ],
            redirect_uri='http://localhost:5000/oauth2callback',
            state=state
        )
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        session['google_credentials'] = credentials_to_dict(credentials)
        session.permanent = True
        # Optionally fetch user info
        try:
            user_info_service = build('oauth2', 'v2', credentials=credentials)
            user_info = user_info_service.userinfo().get().execute()
            session['user_id'] = user_info.get('id')
            session['user_email'] = user_info.get('email')
        except Exception:
            pass
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f"OAuth2 callback error: {e}")
        return jsonify({'status': 'error', 'response': f"Authentication failed: {str(e)}"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/setup')
def setup():
    return render_template('setup.html')

@app.route('/test-calendar')
def test_calendar():
    try:
        service = authenticate_google_calendar()
        if not service:
            return jsonify({
                'status': 'error',
                'response': "🔒 <a href='/login' style='color: #007bff;'>Sign in with Google</a> to test calendar integration"
            })
        event = {
            'summary': 'Test Event from AI Assistant',
            'start': {
                'dateTime': (datetime.now() + rd.relativedelta(hours=1)).isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': (datetime.now() + rd.relativedelta(hours=2)).isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'description': 'This is a test event created to verify Google Calendar integration.'
        }
        event = service.events().insert(calendarId='primary', body=event).execute()
        return jsonify({
            'status': 'success',
            'response': f"✅ Test calendar event created! <a href='{event.get('htmlLink')}' target='_blank' style='color: #007bff;'>View in Calendar</a>"
        })
    except Exception as e:
        logger.error(f"Test calendar error: {e}")
        return jsonify({
            'status': 'error',
            'response': f"❌ Test calendar error: {str(e)}"
        })

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id', 'anonymous')
    stats = {
        'total_reminders': Reminder.query.filter_by(user_id=user_id).count(),
        'completed_reminders': Reminder.query.filter_by(user_id=user_id, completed=True).count(),
        'today_reminders': Reminder.query.filter_by(user_id=user_id).filter(Reminder.time_phrase.ilike('%today%')).count(),
        'total_commands': CommandHistory.query.filter_by(user_id=user_id).count(),
        'active_since': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'google_connected': 'google_credentials' in session
    }
    reminders = Reminder.query.filter_by(user_id=user_id).all()
    history = CommandHistory.query.filter_by(user_id=user_id).order_by(CommandHistory.timestamp.desc()).limit(10).all()
    return render_template('dashboard.html', stats=stats, reminders=reminders, history=history)

@app.route('/status')
def status_check():
    user_id = session.get('user_id', 'anonymous')
    status = {
        'google_connected': 'google_credentials' in session,
        'total_reminders': Reminder.query.filter_by(user_id=user_id).count(),
        'total_commands': CommandHistory.query.filter_by(user_id=user_id).count(),
        'weather_api': 'active',
        'app_version': '1.0.0',
        'environment': app.config['ENV']
    }
    return jsonify(status)

@app.route('/api/process_command', methods=['POST'])
def process_command():
    try:
        user_input = request.json.get('command', '')
        result = handle_command(user_input)
        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Server error in process_command: {e}")
        return jsonify({
            'status': 'error',
            'response': f"❌ Server error: {str(e)}"
        })

if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=5000)