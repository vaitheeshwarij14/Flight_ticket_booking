import os
import json
import smtplib
import cohere
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import speech_recognition as sr
import requests
import soundfile as sf
import spacy
import re

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Use a secure secret key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16MB upload

# Allowed extensions
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'flac', 'ogg'}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), 'secure.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    logger.info("'secure.env' loaded successfully.")
else:
    logger.warning("Warning: 'secure.env' file not found. Email and Cohere functionalities will not work.")

def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Function to convert any audio file to WAV format
def convert_to_wav(audio_file_path):
    """Convert audio file to WAV format."""
    try:
        data, samplerate = sf.read(audio_file_path)
        wav_file_path = os.path.splitext(audio_file_path)[0] + "_converted.wav"
        sf.write(wav_file_path, data, samplerate)
        logger.info(f"Audio file converted to WAV: {wav_file_path}")
        return wav_file_path
    except Exception as e:
        logger.error(f"Error converting audio file: {e}")
        return None

# Function to convert voice to text
def voice_to_text(audio_file_path):
    """Convert audio file to text using Google Speech Recognition."""
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file_path) as source:
        audio_data = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio_data)
            logger.info("Audio converted to text successfully.")
            return text
        except sr.UnknownValueError:
            logger.error("Google Speech Recognition could not understand audio.")
            return None
        except sr.RequestError as e:
            logger.error(f"Could not request results from Google Speech Recognition service; {e}")
            return None

# Load spaCy model
try:
    nlp = spacy.load("en_core_web_sm")
    logger.info("spaCy model loaded successfully.")
except Exception as e:
    logger.error(f"Error loading spaCy model: {e}")
    nlp = None

# Initialize Cohere client
COHERE_API_KEY = os.getenv('COHERE_API_KEY')
if COHERE_API_KEY:
    try:
        cohere_client = cohere.Client(COHERE_API_KEY)
        logger.info("Cohere client initialized successfully.")
    except Exception as e:
        cohere_client = None
        logger.error(f"Error initializing Cohere client: {e}")
else:
    cohere_client = None
    logger.warning("Warning: COHERE_API_KEY not found. Cohere functionalities will not work.")

# Function to extract user data using spaCy
def extract_user_data_spacy(text):
    """Extract user data using spaCy's NER."""
    if not nlp:
        logger.warning("spaCy model not loaded. Skipping spaCy extraction.")
        return {}
    
    doc = nlp(text)
    user_data = {
        'username': None,
        'dob': None,
        'origin': None,
        'destination': None,
        'passport_number': None,
        'seat_preference': None,
        'meal_preference': None,
        'baggage': None
    }

    # Extract entities recognized by spaCy
    for ent in doc.ents:
        if ent.label_ == "PERSON" and not user_data['username']:
            user_data['username'] = ent.text
        elif ent.label_ == "DATE" and not user_data['dob']:
            user_data['dob'] = ent.text
        elif ent.label_ == "GPE":
            if not user_data['origin']:
                user_data['origin'] = ent.text
            elif not user_data['destination']:
                user_data['destination'] = ent.text
        elif ent.label_ == "CARDINAL" and not user_data['baggage']:
            user_data['baggage'] = ent.text + " kg"

    # Note: Since regular expressions are removed, other fields like passport_number,
    # seat_preference, meal_preference are expected to be extracted by Cohere.

    logger.info("User data extracted using spaCy.")
    return user_data

# Function to extract user data using Cohere
def extract_user_data_cohere(text):
    """Extract user data using Cohere's language model."""
    if not cohere_client:
        logger.warning("Cohere client not initialized. Skipping Cohere extraction.")
        return {}
    
    prompt = f"""
Extract the following information from the text below:

- Username
- Date of Birth (DOB)
- Origin
- Destination
- Passport Number
- Seat Preference
- Meal Preference
- Extra Baggage

Provide the information in JSON format as shown below:

{{
    "username": "",
    "dob": "",
    "origin": "",
    "destination": "",
    "passport_number": "",
    "seat_preference": "",
    "meal_preference": "",
    "baggage": ""
}}

Text:
\"\"\"
{text}
\"\"\"
"""

    try:
        response = cohere_client.generate(
            model='command-xlarge',  # Updated to a supported model
            prompt=prompt,
            max_tokens=300,
            temperature=0.0,
            stop_sequences=["}"]
        )
        generated_text = response.generations[0].text.strip()
        
        # Ensure the JSON is properly closed
        if not generated_text.endswith('}'):
            generated_text += '}'
        
        # Safely parse the JSON response
        user_data = json.loads(generated_text)
        logger.info("User data extracted using Cohere.")
        return user_data
    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding failed: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error extracting data with Cohere: {e}")
        return {}

# Combined function to extract user data using both spaCy and Cohere
def extract_user_data(text):
    """Combine data extraction from spaCy and Cohere."""
    user_data_spacy = extract_user_data_spacy(text)
    user_data_cohere = extract_user_data_cohere(text)
    
    # Merge the two dictionaries, giving priority to Cohere's extraction
    merged_user_data = {**user_data_spacy, **user_data_cohere}
    
    # Log the merged data
    logger.info(f"Merged user data: {merged_user_data}")
    return merged_user_data

# Function to retrieve flights from the external API based on origin and destination
def get_flights(origin, destination):
    """Retrieve available flights based on origin and destination."""
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
            logger.info(f"Found {len(filtered_flights)} flights for the route {origin} to {destination}.")
            return filtered_flights
        else:
            if (flight_data.get('origin', '').strip().lower() == origin.lower() and
                flight_data.get('destination', '').strip().lower() == destination.lower()):
                logger.info("Single flight found for the specified route.")
                return [flight_data]
            else:
                logger.info("No flights found for the specified route.")
                return []

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching flight data: {e}")
        return []

# Function to send confirmation email
def send_confirmation_email(sender_email, sender_password, recipient_email, itinerary_details):
    """Send a flight booking confirmation email."""
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
Extra Baggage: {itinerary_details.get('baggage', 'No extra baggage carried.')}

Thank you for choosing our service!

Best regards,
Flight Booking Team
"""
        part = MIMEText(text, "plain")
        message.attach(part)

        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        logger.info("Confirmation email sent successfully!")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

# Route for Home Page - Upload Audio
@app.route('/', methods=['GET', 'POST'])
def upload_audio():
    """Handle audio file upload and processing."""
    if request.method == 'POST':
        if 'audio_file' not in request.files:
            flash('No file part')
            logger.warning("No file part in the request.")
            return redirect(request.url)
        file = request.files['audio_file']
        if file.filename == '':
            flash('No selected file')
            logger.warning("No file selected for upload.")
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            logger.info(f"File saved to {filepath}")

            # Convert to WAV
            wav_file_path = convert_to_wav(filepath)
            if not wav_file_path:
                flash('Failed to convert audio file to WAV.')
                logger.error("Failed to convert audio file to WAV.")
                return redirect(request.url)

            # Convert voice to text
            text = voice_to_text(wav_file_path)
            if not text:
                flash('Could not convert audio to text.')
                logger.error("Could not convert audio to text.")
                return redirect(request.url)

            # Extract user data using spaCy and Cohere
            user_data = extract_user_data(text)
            required_fields = ['username', 'origin', 'destination', 'passport_number']
            missing_fields = [field for field in required_fields if not user_data.get(field)]

            if missing_fields:
                flash(f"Could not extract the following fields: {', '.join(missing_fields)}")
                logger.warning(f"Missing fields after data extraction: {missing_fields}")
                return redirect(request.url)

            # Get available flights
            available_flights = get_flights(user_data['origin'], user_data['destination'])
            if not available_flights:
                flash("No flights available for the selected route.")
                logger.info("No flights available for the selected route.")
                return redirect(request.url)

            # Store data in session
            session['text'] = text
            session['user_data'] = user_data
            session['available_flights'] = available_flights

            # Redirect to flights page
            return redirect(url_for('select_flight'))

        else:
            flash('Invalid file type. Please upload a valid audio file.')
            logger.warning("Invalid file type uploaded.")
            return redirect(request.url)

    return render_template('upload.html')

# Route to select flight and enter recipient email
@app.route('/select_flight', methods=['GET', 'POST'])
def select_flight():
    """Handle flight selection and email confirmation."""
    if request.method == 'POST':
        selected_flight = request.form.get('flight')
        recipient_email = request.form.get('email').strip()

        if not selected_flight:
            flash("No flight selected.")
            logger.warning("No flight selected by the user.")
            return redirect(request.url)

        if not re.match(r"[^@]+@[^@]+\.[^@]+", recipient_email):
            flash("Invalid email address.")
            logger.warning(f"Invalid email address entered: {recipient_email}")
            return redirect(request.url)

        # Retrieve flight details
        available_flights = session.get('available_flights', [])
        selected_flight_details = next((flight for flight in available_flights if flight.get('flight_number') == selected_flight), None)

        if not selected_flight_details:
            flash("Selected flight not found.")
            logger.error(f"Selected flight number {selected_flight} not found in available flights.")
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
            'meal_preference': user_data.get('meal_preference', 'No meal preference specified.'),
            'baggage': user_data.get('baggage', 'No extra baggage carried.')
        }

        # Send confirmation email
        sender_email = os.getenv('SENDER_EMAIL')
        sender_password = os.getenv('SENDER_PASSWORD')

        if not sender_email or not sender_password:
            flash("Email credentials not found. Please configure 'secure.env'.")
            logger.error("Email credentials not found in environment variables.")
            return redirect(request.url)

        email_sent = send_confirmation_email(sender_email, sender_password, recipient_email, itinerary_details)

        if email_sent:
            # Store itinerary and recipient email in session
            session['itinerary_details'] = itinerary_details
            session['recipient_email'] = recipient_email
            logger.info(f"Confirmation email sent to {recipient_email}.")
            return redirect(url_for('confirmation'))
        else:
            flash("Failed to send confirmation email.")
            logger.error("Failed to send confirmation email.")
            return redirect(request.url)

    # GET request
    text = session.get('text', '')
    available_flights = session.get('available_flights', [])
    user_data = session.get('user_data', {})

    return render_template('flights.html', text=text, flights=available_flights, user_data=user_data)

# Route for Confirmation Page
@app.route('/confirmation', methods=['GET'])
def confirmation():
    """Display confirmation of the flight booking."""
    itinerary = session.get('itinerary_details', {})
    recipient_email = session.get('recipient_email', '')
    return render_template('confirmation.html', itinerary=itinerary, recipient_email=recipient_email)

# Main entry point
if __name__ == '__main__':
    load_dotenv(dotenv_path)
    app.run(debug=True)
