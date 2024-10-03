import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import speech_recognition as sr
import requests
import soundfile as sf
from transformers import pipeline

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

# Function to extract user data using Hugging Face transformers
def extract_user_data(text):
    nlp = pipeline("ner", model="dbmdz/bert-large-cased-finetuned-conll03-english")
    entities = nlp(text)

    user_data = {
        'username': None,
        'dob': None,
        'origin': None,
        'destination': None,
        'passport_number': None,
        'seat_preference': None,
        'meal_preference': None
    }

    for entity in entities:
        if entity['entity'] == 'B-PER':
            user_data['username'] = entity['word']
        elif entity['entity'] == 'B-DATE':
            user_data['dob'] = entity['word']
        # Add other entity extractions based on your model and requirements here

    # Custom parsing for origin and destination
    parts = text.split()
    for i, part in enumerate(parts):
        if part.lower() in ["from", "origin"]:
            user_data['origin'] = parts[i + 1]  # Next part is the origin
        elif part.lower() == "to":
            user_data['destination'] = parts[i + 1]  # Next part is the destination

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
            'origin_to_destination': f"{user_data.get('origin')} to {user_data.get('destination')}",
            'departure_date': selected_flight_details.get('departure_date', 'Unknown'),
            'seat_preference': selected_flight_details.get('seat_preference', 'Unknown'),
            'meal_preference': selected_flight_details.get('meal_preference', 'Unknown'),
        }

        # Send confirmation email
        sender_email = os.getenv('EMAIL_USER')
        sender_password = os.getenv('EMAIL_PASS')

        email_sent = send_confirmation_email(sender_email, sender_password, recipient_email, itinerary_details)

        if email_sent:
            flash("Flight booked successfully! A confirmation email has been sent.")
        else:
            flash("Failed to send confirmation email.")

        return redirect(url_for('upload_audio'))

    available_flights = session.get('available_flights', [])
    return render_template('select_flight.html', flights=available_flights)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
