# firebase_utils.py
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional
import tempfile

# Try to import Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, db
    from firebase_admin.exceptions import FirebaseError
    
    # Check if Firebase is initialized
    if not firebase_admin._apps:
        # You'll need to initialize Firebase here or pass config
        pass
    
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False


class FirebaseJobManager:
    """Handle Firebase operations for job forms"""
    
    @staticmethod
    def save_job_form(job_data: dict) -> bool:
        """Save job form data to Firebase"""
        if not FIREBASE_AVAILABLE:
            print("✗ Firebase not available - job form not saved")
            return False
            
        try:
            ref = db.reference('/job_forms')
            
            # Check if job already exists (by job_number)
            existing_jobs = ref.order_by_child('job_number').equal_to(job_data['job_number']).get()
            
            if existing_jobs:
                # Update existing job
                job_id = list(existing_jobs.keys())[0]
                job_data['updated_at'] = datetime.now().isoformat()
                ref.child(job_id).update(job_data)
                print(f"✓ Job form updated in Firebase: {job_data['job_number']}")
                return True
            else:
                # Create new job
                new_job_ref = ref.push()
                job_data['firebase_id'] = new_job_ref.key
                job_data['created_at'] = datetime.now().isoformat()
                job_data['updated_at'] = datetime.now().isoformat()
                new_job_ref.set(job_data)
                print(f"✓ Job form saved to Firebase with ID: {new_job_ref.key}")
                return True
        except Exception as e:
            print(f"✗ Error saving job form to Firebase: {e}")
            return False
    
    @staticmethod
    def save_job_pdf_to_firebase(job_number: str, pdf_path: Path) -> bool:
        """Save job form PDF to Firebase Realtime Database as Base64"""
        if not FIREBASE_AVAILABLE:
            print("✗ Firebase not available - job PDF not saved")
            return False
            
        try:
            # Read PDF file
            with open(pdf_path, "rb") as pdf_file:
                pdf_data = pdf_file.read()
            
            # Convert PDF to base64 for storage in Firebase Realtime Database
            pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
            
            # Save to Firebase under /job_pdfs node
            ref = db.reference('/job_pdfs')
            pdf_record = {
                'job_number': job_number,
                'pdf_base64': pdf_base64,
                'file_name': f"{job_number}_job_form.pdf",
                'created_at': datetime.now().isoformat(),
                'size_bytes': len(pdf_data)
            }
            
            # Check if PDF already exists
            existing_pdfs = ref.order_by_child('job_number').equal_to(job_number).get()
            
            if existing_pdfs:
                # Update existing PDF
                pdf_id = list(existing_pdfs.keys())[0]
                ref.child(pdf_id).update(pdf_record)
                print(f"✓ Job PDF updated in Firebase: {job_number}")
            else:
                # Create new PDF entry
                new_pdf_ref = ref.push()
                pdf_record['firebase_id'] = new_pdf_ref.key
                new_pdf_ref.set(pdf_record)
                print(f"✓ Job PDF saved to Firebase with ID: {new_pdf_ref.key}")
            
            return True
            
        except Exception as e:
            print(f"✗ Error saving job PDF to Firebase: {e}")
            return False