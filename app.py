from flask import Flask, request, jsonify
from flask_cors import CORS
import os.path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import qrcode
import base64
from io import BytesIO
import dotenv
from datetime import datetime

dotenv.load_dotenv()

# Define the scopes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Read the environment variables
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
RANGE_NAME = os.getenv("RANGE_NAME")
SHEET_REGISTERS = os.getenv("SHEET_REGISTERS")

SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")
TEMPLATE_ID = os.getenv('SENDGRID_TEMPLATE_ID')

# Path to the service account credentials file
SERVICE_ACCOUNT_FILE = 'token.json'

BASE_URL = os.getenv("BASE_URL")

sg = SendGridAPIClient(SENDGRID_API_KEY)


app = Flask(__name__)
CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'


def get_credentials():
    return Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)


def get_sheet():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def get_values():   # Call the Sheets API
    try:
        service = get_sheet()
        sheet = service.spreadsheets()
        result = (
            sheet.values()
            .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME)
            .execute()
        )
        return result.get("values", []) # Return a list with the values from the spreadsheet
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []


def get_spreadsheet_data():  # Get the values from the spreadsheet and return them as a JSON
    values = get_values()
    if not values:
        return jsonify({"error": "No se encontraron datos."})
    else:
        headers = values[0]
        records = []

        for row in values[1:]:
            record = {header: value for header, value in zip(headers, row)}
            records.append(record)

        return jsonify(records)


def add_register(data):
    try:
        service = get_sheet()
        sheet = service.spreadsheets()

        items = data.get('items', [])
        items_str = ', '.join([f"{item['id']} (Qty: {item['quantity']})" for item in items])
        subtotal = data.get('subtotal', '')
        formData = data.get('formData', {})
        date  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row = [
            formData.get('workshopTitle', ''),
            formData.get('name', ''),
            formData.get('email', ''),
            items_str,
            subtotal,
            date
        ]

        body = {
            "values": [row]
        }
        result = sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=SHEET_REGISTERS,
            valueInputOption="RAW",
            body=body
        ).execute()
        return result
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


def send_email(body):
    data = {
        "personalizations": [
            {
                "to": [{"email": body['formData']['email']}],
                "bcc": [{"email": "REPLACEME_WITH_THE_EMAIL_COPY"},
                        {"email": "REPLACEME_WITH_THE_EMAIL_COPY"}],
                "dynamic_template_data": body
            }
        ],
        "from": {"email": FROM_EMAIL},
        "template_id": TEMPLATE_ID,
    }
    try:
        response = sg.send(data)
        print(response.status_code)
        print(response.body)
        print(response.headers)
        return response.status_code
    except Exception as e:
        print(e.message)
        return response.status_code


def generate_qr_base64(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Convertir la imagen a base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue())

    return img_base64.decode()

@app.route(f"/{BASE_URL}/items", methods=["GET"])
def get_items():
    values = get_values()
    if not values:
        return jsonify({"error": "No se encontraron datos."})
    else:
        # The 'Items' column is the seventh column (index 6)
        items = values[6]
        return jsonify({"items": items})


# Return the values from the spreadsheet as a JSON
@app.route(f"/{BASE_URL}", methods=["GET"])
def get_data():
    return get_spreadsheet_data()


# Receive the form data and send it via email
@app.route(f"/{BASE_URL}/send-email", methods=["POST"])
def send_email_from_form():
    data = request.json

    result = add_register(data)
    if result:
        print("Data added successfully.")
    else:
        print("An error occurred while adding the data.")

    data['qr'] = f"data:image/png;base64,{generate_qr_base64(data)}"
    status_code = send_email(data)
    return jsonify({"status_code": status_code, "message": "Email sent successfully" if status_code == 202 else "Email not sent"})


if __name__ == "__main__":
    app.run(debug=True)
