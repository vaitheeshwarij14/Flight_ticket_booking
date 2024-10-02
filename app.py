import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import speech_recognition as sr
import requests
import soundfile as sf
import openai  # Importing OpenAI API

app = Flask(__name__)
app.secret_key = 'pgay wtpq kpiq vlze'  # Replace with a secure secret key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16MB upload

# Allowed extensions
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'flac', 'ogg'}

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), 'secure.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    print("Warning: 'secure.env' file not found. Email functionality will not work.")

# OpenAI API key
openai.api_key = os.getenv('OPENAI_API_KEY')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Function to convert any audio file to WAV format
def convert_to_wav(audio_file_path):
    try:
        data, samplerate = sf.read(audio_file_path)
        wav_file_path = os.path.splitext(audio_file_path)[0] + "_converted.wav"
        sf.write(wav_file_path, data, samplerate)
        return wav_file_path
    except Exception as e:
        print(f"Error converting audio file: {e}")
        return None

# Function to convert voice to text using an LLM (like GPT-4)
def voice_to_text_with_llm(audio_file_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file_path) as source:
        audio_data = recognizer.record(source)
        try:
            # Convert speech to text using Google Speech Recognition
            initial_text = recognizer.recognize_google(audio_data)
            print("\nInitial Converted Text:\n", initial_text)

            # Send text to LLM (e.g., GPT-4) for refinement and processing
            refined_text = call_llm_for_text_enhancement(initial_text)
            print("\nRefined Text from LLM:\n", refined_text)

            return refined_text
        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")
            return None
        except sr.RequestError as e:
            print(f"Could not request results from Google Speech Recognition service; {e}")
            return None

# Function to call an LLM (GPT-4) to refine the text
def call_llm_for_text_enhancement(text):
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",  # Or use "gpt-4" if available
            prompt=f"Please enhance and format the following text for better clarity and detail: {text}",
            max_tokens=150,
            n=1,
            stop=None,
            temperature=0.5
        )
        return response.choices[0].text.strip()
    except Exception as e:
        print(f"Error calling LLM: {e}")
        return text

# Function to extract user data from the refined text
def extract_user_data(text):
    patterns = {
        'username': r'(?:my name is|username is)\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)*?)\b(?=\s+(?:and|I|born|,|\.|$))',
        'dob': r'(?:born on|date of birth is|date of birth)\s*([A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?(?:,|\s)\s*\d{4})',
        'origin_to_destination': r'(?:from|origin is)\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s+to\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*?)\b(?=\s+(?:my|passport|I)|\.|\s|$)',
        'passport_number': r'(?:passport number is|passport number:)\s*([A-Za-z0-9]+)',
        'seat_preference': r'(?:seat preference is|prefer a)\s*(window|aisle|middle)(?:\s+seat)?',
        'meal_preference': r'(?:meal preference is|would like)\s*([A-Za-z\s]+?)(?=\s+(?:during|to|carry|number|kilograms|$))'
    }

    user_data = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if field == 'origin_to_destination':
                user_data['origin'] = match.group(1).strip()
                user_data['destination'] = match.group(2).strip()
            else:
                value = match.group(1).strip()
                user_data[field] = value
        else:
            user_data[field] = None

    return user_data

# Function to retrieve flights from the external API based on origin and destination
def get_flights(origin, destination):
    url = "https://134fd915-ea3b-4cca-a95d-54b5d54eb568.mock.pstmn.io/flight_details"
    try:
        params = {
            'origin': origin,
            'destination': destination
        }
        response = requests.get(url, params=params)
        response.raise_for_status()

        flight_data = response.json()

        if isinstance(flight_data, list):
            filtered_flights = [
                flight for flight in flight_data
                if flight.get('origin', '').strip().lower() == origin.lower() and
                   flight.get('destination', '').strip().lower() == destination.lower()
            ]
            return filtered_flights
        else:
            if (flight_data.get('origin', '').strip().lower() == origin.lower() and
                flight_data.get('destination', '').strip().lower() == destination.lower()):
                return [flight_data]
            else:
                return []

    except requests.exceptions.RequestException as e:
        print(f"Error fetching flight data: {e}")
        return []

# Route for Home Page - Upload Audio
@app.route('/', methods=['GET', 'POST'])
def upload_audio():
    if request.method == 'POST':
        if 'audio_file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['audio_file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            print(f"File saved to {filepath}")

            # Convert to WAV
            wav_file_path = convert_to_wav(filepath)
            if not wav_file_path:
                flash('Failed to convert audio file to WAV.')
                return redirect(request.url)

            # Convert voice to text using LLM model
            text = voice_to_text_with_llm(wav_file_path)
            if not text:
                flash('Could not convert audio to text.')
                return redirect(request.url)

            # Extract user data
            user_data = extract_user_data(text)
            required_fields = ['username', 'origin', 'destination', 'passport_number']
            missing_fields = [field for field in required_fields if not user_data.get(field)]

            if missing_fields:
                flash(f"Could not extract the following fields: {', '.join(missing_fields)}")
                return redirect(request.url)

            # Get available flights
            available_flights = get_flights(user_data['origin'], user_data['destination'])
            if not available_flights:
                flash("No flights available for the selected route.")
                return redirect(request.url)

            # Store data in session
            session['text'] = text
            session['user_data'] = user_data
            session['available_flights'] = available_flights

            # Redirect to flights page
            return redirect(url_for('select_flight'))

        else:
            flash('Invalid file type. Please upload a valid audio file.')
            return redirect(request.url)

    return render_template('upload.html')

# Route to select flight and enter recipient email
@app.route('/select_flight', methods=['GET', 'POST'])
def select_flight():
    if request.method == 'POST':
        selected_flight = request.form.get('flight')
        recipient_email = request.form.get('email').strip()

        if not selected_flight:
            flash("No flight selected.")
            return redirect(request.url)

        if not re.match(r"[^@]+@[^@]+\.[^@]+", recipient_email):
            flash("Invalid email address.")
            return redirect(request.url)

        session['selected_flight'] = selected_flight
        session['recipient_email'] = recipient_email

        # Redirect to confirmation page
        return redirect(url_for('confirmation'))

    # Retrieve session data
    available_flights = session.get('available_flights', [])
    user_data = session.get('user_data', {})

    return render_template('flights.html', flights=available_flights, user_data=user_data)

# Route for flight confirmation and email sending
@app.route('/confirmation', methods=['GET', 'POST'])
def confirmation():
    selected_flight = session.get('selected_flight', None)
    user_data = session.get('user_data', {})
    recipient_email = session.get('recipient_email', None)

    # Create itinerary from selected flight and user data
    itinerary = {
        'username': user_data.get('username'),
        'flight_number': selected_flight,  # Assuming selected_flight contains the flight number
        'flight_name': "Flight XYZ",  # Placeholder for flight name, adjust accordingly
        'origin_to_destination': f"{user_data.get('origin')} to {user_data.get('destination')}",
        'departure_date': "2024-10-01",  # Placeholder for departure date, adjust accordingly
        'seat_preference': user_data.get('seat_preference', 'N/A'),
        'meal_preference': user_data.get('meal_preference', 'N/A'),
    }

    if request.method == 'POST':
        # Send flight details to recipient email
        if send_flight_details_email(user_data, itinerary, recipient_email):
            flash('Email sent successfully!')
        else:
            flash('Failed to send email.')

        return redirect(url_for('upload_audio'))

    return render_template('confirmation.html', itinerary=itinerary, recipient_email=recipient_email)

# Function to send flight details via email
def send_flight_details_email(user_data, itinerary, recipient_email):
    try:
        email_user = os.getenv('EMAIL_USER')
        email_password = os.getenv('EMAIL_PASSWORD')
        email_host = os.getenv('EMAIL_HOST')
        email_port = os.getenv('EMAIL_PORT')

        if not all([email_user, email_password, email_host, email_port]):
            print("Email configuration missing in secure.env")
            return False

        msg = MIMEMultipart()
        msg['From'] = email_user
        msg['To'] = recipient_email
        msg['Subject'] = 'Flight Booking Confirmation'

        body = f"""
        Dear {itinerary['username']},

        Your flight booking is confirmed. Below are the details:

        Flight Number: {itinerary['flight_number']}
        Flight Name: {itinerary['flight_name']}
        Route: {itinerary['origin_to_destination']}
        Departure Date: {itinerary['departure_date']}
        Passport Number: {user_data['passport_number']}
        Seat Preference: {itinerary['seat_preference']}
        Meal Preference: {itinerary['meal_preference']}

        Thank you for booking with us!

        Best regards,
        The Flight Team
        """

        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(email_host, int(email_port))
        server.starttls()
        server.login(email_user, email_password)
        server.sendmail(email_user, recipient_email, msg.as_string())
        server.quit()

        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

if __name__ == '__main__':
    app.run(debug=True)
