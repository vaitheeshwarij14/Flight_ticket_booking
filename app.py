import os
import re
import smtplib
import cohere
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import speech_recognition as sr
import requests
import soundfile as sf
import spacy

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
    print("Warning: 'secure.env' file not found. Email and Cohere functionalities will not work.")

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

# Load spaCy model
nlp = spacy.load("en_core_web_sm")

# Initialize Cohere client
COHERE_API_KEY = os.getenv('COHERE_API_KEY')
if COHERE_API_KEY:
    cohere_client = cohere.Client(COHERE_API_KEY)
else:
    cohere_client = None
    print("Warning: COHERE_API_KEY not found. Cohere functionalities will not work.")

# Function to extract user data using spaCy
def extract_user_data_spacy(text):
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

    # Custom extraction for passport number
    passport_pattern = re.compile(r'(passport number is|passport number:)\s*([A-Za-z0-9]+)', re.IGNORECASE)
    passport_match = passport_pattern.search(text)
    if passport_match:
        user_data['passport_number'] = passport_match.group(2).strip()

    # Custom extraction for seat preference
    seat_pattern = re.compile(r'(prefer a|seat preference is)\s*(window|aisle|middle)', re.IGNORECASE)
    seat_match = seat_pattern.search(text)
    if seat_match:
        user_data['seat_preference'] = seat_match.group(2).strip().lower()

    # Custom extraction for meal preference
    meal_pattern = re.compile(r'(vegetarian|non-vegetarian|vegan|gluten-free|halal)', re.IGNORECASE)
    meal_match = meal_pattern.search(text)
    if meal_match:
        user_data['meal_preference'] = meal_match.group(1).strip().lower()

    # Custom extraction for baggage
    baggage_pattern = re.compile(r'carry extra\s*(\d+)\s*(kilograms|kg|kgs)', re.IGNORECASE)
    baggage_match = baggage_pattern.search(text)
    if baggage_match:
        user_data['baggage'] = f"{baggage_match.group(1)} {baggage_match.group(2)}"

    return user_data

# Function to extract user data using Cohere
def extract_user_data_cohere(text):
    if not cohere_client:
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
            model='large',
            prompt=prompt,
            max_tokens=300,
            temperature=0.0,
            stop_sequences=["}"]
        )
        generated_text = response.generations[0].text
        # Ensure the JSON is properly closed
        if not generated_text.strip().endswith('}'):
            generated_text += '}'
        user_data = eval(generated_text)  # Note: using eval can be dangerous; consider using json.loads with proper formatting
        return user_data
    except Exception as e:
        print(f"Error extracting data with Cohere: {e}")
        return {}

# Combined function to extract user data using both spaCy and Cohere
def extract_user_data(text):
    user_data_spacy = extract_user_data_spacy(text)
    user_data_cohere = extract_user_data_cohere(text)
    
    # Merge the two dictionaries, giving priority to Cohere's extraction
    merged_user_data = {**user_data_spacy, **user_data_cohere}
    
    return merged_user_data

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
Extra Baggage: {itinerary_details.get('baggage', 'No extra baggage carried.')}

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

            # Extract user data using spaCy and Cohere
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
            'meal_preference': user_data.get('meal_preference', 'No meal preference specified.'),
            'baggage': user_data.get('baggage', 'No extra baggage carried.')
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

if __name__ == '__main__':
    load_dotenv()
    app.run(debug=True)
