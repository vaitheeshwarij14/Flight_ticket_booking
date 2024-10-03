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

app = Flask(_name_)
app.secret_key = 'pgay wtpq kpiq vlze'  # Replace with a secure secret key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16MB upload

# Allowed extensions
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'flac', 'ogg'}

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(_file_), 'secure.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    print("Warning: 'secure.env' file not found. Email functionality will not work.")

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

# Function to convert voice to text
def voice_to_text(audio_file_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file_path) as source:
        audio_data = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio_data)
            print("\nConverted Text:\n", text)
            return text
        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")
            return None
        except sr.RequestError as e:
            print(f"Could not request results from Google Speech Recognition service; {e}")
            return None

# Function to extract user data from text with improved regex patterns
def extract_user_data(text):
    patterns = {
        'username': r'(?:my name is|username is)\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)*?)\b(?=\s+(?:and|I|born|,|\.|$))',
        'dob': r'(?:born on|date of birth is|date of birth)\s*([A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?(?:,|\s)\s*\d{4})',
        'origin_to_destination': r'(?:from|origin is)\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+))\s+to\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b(?=\s+(?:my|passport|I)|\.|\s|$)',
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

# Function to send confirmation email
def send_confirmation_email(sender_email, sender_password, recipient_email, itinerary_details):
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)

        message = MIMEMultipart("alternative")
        message["Subject"] = "Flight Booking Confirmation"
        message["From"] = sender_email
        message["To"] = recipient_email

        text = f"""\
Dear {itinerary_details['username']},

Your flight has been successfully booked with the following details:

Flight Number: {itinerary_details['flight_number']}
Flight Name: {itinerary_details['flight_name']}
Origin to Destination: {itinerary_details['origin_to_destination']}
Departure Date: {itinerary_details['departure_date']}
Seat Preference: {itinerary_details['seat_preference']}
Meal Preference: {itinerary_details['meal_preference']}

Thank you for choosing our service!

Best regards,
Flight Booking Team
"""
        part = MIMEText(text, "plain")
        message.attach(part)

        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        print("Confirmation email sent successfully!")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

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

            # Convert voice to text
            text = voice_to_text(wav_file_path)
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

        # Retrieve flight details
        available_flights = session.get('available_flights', [])
        selected_flight_details = next((flight for flight in available_flights if flight.get('flight_number') == selected_flight), None)

        if not selected_flight_details:
            flash("Selected flight not found.")
            return redirect(request.url)

        # Prepare itinerary details
        user_data = session.get('user_data', {})
        itinerary_details = {
            'username': user_data.get('username', 'Unknown'),
            'flight_number': selected_flight_details.get('flight_number', 'Unknown'),
            'flight_name': selected_flight_details.get('flight_name', 'Unknown'),
            'origin_to_destination': f"{user_data.get('origin', 'Unknown')} to {user_data.get('destination', 'Unknown')}",
            'departure_date': selected_flight_details.get('departure_date', 'Unknown'),
            'seat_preference': user_data.get('seat_preference', 'No seat preference specified.'),
            'meal_preference': user_data.get('meal_preference', 'No meal preference specified.')
        }

        # Send confirmation email
        sender_email = os.getenv('SENDER_EMAIL')
        sender_password = os.getenv('SENDER_PASSWORD')

        if not sender_email or not sender_password:
            flash("Email credentials not found. Please configure 'secure.env'.")
            return redirect(request.url)

        email_sent = send_confirmation_email(sender_email, sender_password, recipient_email, itinerary_details)

        if email_sent:
            # Store itinerary and recipient email in session
            session['itinerary_details'] = itinerary_details
            session['recipient_email'] = recipient_email
            return redirect(url_for('confirmation'))
        else:
            flash("Failed to send confirmation email.")
            return redirect(request.url)

    # GET request
    text = session.get('text', '')
    available_flights = session.get('available_flights', [])
    user_data = session.get('user_data', {})

    return render_template('flights.html', text=text, flights=available_flights, user_data=user_data)

# Route for Confirmation Page
@app.route('/confirmation', methods=['GET'])
def confirmation():
    itinerary = session.get('itinerary_details', {})
    recipient_email = session.get('recipient_email', '')
    return render_template('confirmation.html', itinerary=itinerary, recipient_email=recipient_email)

if _name_ == '_main_':
    load_dotenv()
    app.run(debug=True)
