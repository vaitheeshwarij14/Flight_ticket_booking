
# AI Flight Ticket Booking

## Overview

This project implements an Agentic AI Workflow for Voice-Based Flight Ticket Booking. The application takes an audio file containing flight booking details, processes it, and confirms the availability of flights.

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.x
- pip (Python package installer)

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/vaitheeshwarij14/AI_Flight_ticket_booking.git
   cd AI_Flight_ticket_booking
   ```

2. Install the required packages:

   ```bash
   pip install -r requirements.txt
   ```

3. Set up your environment variables:

   - Create a file named `secure.env` in the root directory.
   - Add your credentials in the following format:

     ```plaintext
     SENDER_EMAIL=<Sender_Email_id>
     SENDER_PASSWORD=<Sender_password>
     COHERE_API_KEY=<Cohere_API_Key>
     ```

## Usage

1. Prepare your audio file containing the details to book flights.
2. Place the audio file in the appropriate directory.
3. Run the application:

   ```bash
   python app.py
   ```

## Images

Below are some images related to the project:

1. **Run app.py**

   ![Image 1](images/img1.png)

2. **Choose the audio file and click on Upload and Process.**

   ![Image 2](images/img2.png)

3. **Choose a flight from the available options, provide the recipient's email address, and click Book Flight and Send Confirmation.**

   ![Image 3](images/img3.png)

4. **This window confirms that your booking is complete and reminds you to check your email for the confirmation details.**

   ![Image 4](images/img4.png)

5. **This is the confirmation email that you will receive.**

   ![Image 5](images/img5.png)

## Documentation

For further details, refer to the project documentation [here](https://docs.google.com/document/d/1J8zje3sAPO5qVAIn9A5xuCSgcBzc2G40EDChHBkAsis/edit#heading=h.nnycgcqdyw4f).
