# test_login.py
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import FIREBASE_AVAILABLE, FirebaseManager, db
from auth_utils import hash_password, verify_password

def test_login():
    print("\n" + "="*60)
    print("🧪 TESTING LOGIN DIRECTLY")
    print("="*60)
    
    email = "ashajyothi.gadhi@gmail.com"
    password = "admin123"
    
    print(f"\nTesting with:")
    print(f"  Email: {email}")
    print(f"  Password: {password}")
    
    # Test hash generation
    print("\n📝 Testing Hash Generation:")
    generated_hash = hash_password(password)
    print(f"  Generated hash: {generated_hash}")
    
    # Expected hash for "admin123"
    expected_hash = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
    print(f"  Expected hash:  {expected_hash}")
    print(f"  Match: {generated_hash == expected_hash}")
    
    if not FIREBASE_AVAILABLE:
        print("\n❌ Firebase is not available!")
        return
    
    # Check Firebase
    print("\n📁 Checking Firebase:")
    try:
        ref = db.reference('/users')
        users = ref.order_by_child('email').equal_to(email).get()
        
        if not users:
            print(f"  ❌ No user found with email: {email}")
            return
        
        for user_id, user_data in users.items():
            print(f"  ✅ User found!")
            print(f"     Username: {user_data.get('username')}")
            print(f"     Email: {user_data.get('email')}")
            stored_hash = user_data.get('password_hash', '')
            print(f"     Stored hash: {stored_hash}")
            
            # Test verification
            result = verify_password(password, stored_hash)
            print(f"\n🔐 Verification result: {result}")
            
            if result:
                print("\n✅ LOGIN WOULD SUCCEED!")
            else:
                print("\n❌ LOGIN WOULD FAIL - Password mismatch!")
                print(f"   Generated: {generated_hash}")
                print(f"   Stored:    {stored_hash}")
                
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_login()