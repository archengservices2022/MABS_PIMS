"""
Login Diagnostic Tool
Helps troubleshoot and fix login issues with Firebase authentication
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime

def test_firebase_availability():
    """Test if Firebase is properly configured"""
    print("🔍 Testing Firebase Configuration...")
    
    try:
        import firebase_admin
        from firebase_admin import credentials, db
        print("✅ Firebase SDK imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Firebase SDK not available: {e}")
        return False

def test_firebase_config():
    """Test Firebase configuration"""
    print("\n🔍 Testing Firebase Configuration...")
    
    try:
        # Try to import FIREBASE_CONFIG
        sys.path.insert(0, str(Path(__file__).parent))
        from main import FIREBASE_CONFIG
        
        if not FIREBASE_CONFIG:
            print("❌ FIREBASE_CONFIG is empty")
            return False
        
        required_keys = ["apiKey", "authDomain", "databaseURL", "projectId"]
        missing_keys = []
        
        for key in required_keys:
            if key not in FIREBASE_CONFIG or not FIREBASE_CONFIG[key]:
                missing_keys.append(key)
        
        if missing_keys:
            print(f"❌ Missing Firebase config keys: {missing_keys}")
            return False
        
        print("✅ Firebase configuration looks complete")
        print(f"   - Project ID: {FIREBASE_CONFIG.get('projectId')}")
        print(f"   - Database URL: {FIREBASE_CONFIG.get('databaseURL')}")
        return True
        
    except Exception as e:
        print(f"❌ Error checking Firebase config: {e}")
        return False

def test_firebase_auth_api():
    """Test Firebase Authentication API"""
    print("\n🔍 Testing Firebase Auth API...")
    
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from main import FIREBASE_CONFIG
        
        api_key = FIREBASE_CONFIG.get("apiKey")
        if not api_key:
            print("❌ No API key found in config")
            return False
        
        # Test with a simple request to check if API is reachable
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
        
        # Send a test request with invalid credentials to check API response
        test_payload = {
            "email": "test@example.com",
            "password": "invalid_password",
            "returnSecureToken": True
        }
        
        response = requests.post(url, json=test_payload, timeout=10)
        
        if response.status_code == 400:
            print("✅ Firebase Auth API is responding (400 expected for invalid credentials)")
            return True
        elif response.status_code == 200:
            print("⚠️  Unexpected success response")
            return True
        else:
            print(f"❌ Firebase Auth API returned status {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ Firebase Auth API timeout")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Firebase Auth API")
        return False
    except Exception as e:
        print(f"❌ Error testing Firebase Auth API: {e}")
        return False

def test_local_users():
    """Test local user configuration"""
    print("\n🔍 Testing Local User Configuration...")
    
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from main import Config
        
        if not hasattr(Config, 'USERS') or not Config.USERS:
            print("❌ No users found in local configuration")
            return False
        
        users = Config.USERS
        print(f"✅ Found {len(users)} users in local configuration")
        
        for username, user_data in users.items():
            print(f"   - {username}: {user_data.get('role', 'unknown role')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking local users: {e}")
        return False

def create_fallback_login():
    """Create a fallback login solution"""
    print("\n🔧 Creating Fallback Login Solution...")
    
    try:
        # Create a simple local authentication bypass
        fallback_code = '''
# Fallback Login - Add to main.py before the LoginWindow class
class FallbackAuth:
    @staticmethod
    def validate_user_local(email: str, password: str) -> tuple:
        """Fallback local authentication when Firebase is unavailable"""
        try:
            from main import Config, normalize_role
            
            # Check local users
            for username, user_data in Config.USERS.items():
                user_email = user_data.get('email', '').lower()
                if user_email == email.lower():
                    # Simple password check (in production, use proper hashing)
                    stored_password = user_data.get('password', '')
                    if stored_password == password:
                        role = normalize_role(user_data.get('role', 'sales'))
                        return (True, username, email, role)
            
            return (False, "", "", "")
        except Exception as e:
            print(f"Fallback auth error: {e}")
            return (False, "", "", "")

# Modify validate_user_email to use fallback
original_validate = FirebaseManager.validate_user_email

def validate_user_email_with_fallback(email: str, password: str) -> tuple:
    """Enhanced validation with fallback"""
    # Try Firebase first
    try:
        result = original_validate(email, password)
        if result[0]:  # Success
            return result
    except Exception:
        pass
    
    # Use fallback if Firebase fails
    print("Using fallback authentication...")
    return FallbackAuth.validate_user_local(email, password)

# Replace the original method
FirebaseManager.validate_user_email = validate_user_email_with_fallback
'''
        
        fallback_file = Path(__file__).parent / "fallback_login.py"
        with open(fallback_file, 'w') as f:
            f.write(fallback_code)
        
        print(f"✅ Fallback login code saved to {fallback_file}")
        print("   Instructions:")
        print("   1. Copy the code from fallback_login.py")
        print("   2. Paste it into main.py before the LoginWindow class")
        print("   3. Restart the application")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating fallback: {e}")
        return False

def create_test_user():
    """Create a test user for login"""
    print("\n🔧 Creating Test User...")
    
    try:
        test_user = {
            "admin": {
                "email": "admin@mabs.com",
                "password": "admin123",
                "role": "admin",
                "active": True
            },
            "sales": {
                "email": "sales@mabs.com", 
                "password": "sales123",
                "role": "sales",
                "active": True
            }
        }
        
        settings_file = Path(__file__).parent / "data" / "settings.json"
        settings_file.parent.mkdir(exist_ok=True)
        
        # Load existing settings
        settings = {}
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = json.load(f)
        
        # Add test users
        if 'users' not in settings:
            settings['users'] = {}
        
        settings['users'].update(test_user)
        
        # Save settings
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=2)
        
        print("✅ Test users created:")
        print("   - Email: admin@mabs.com, Password: admin123, Role: admin")
        print("   - Email: sales@mabs.com, Password: sales123, Role: sales")
        print(f"   - Saved to: {settings_file}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating test user: {e}")
        return False

def main():
    """Run diagnostic tests"""
    print("🚀 MABS Engineering - Login Diagnostic Tool")
    print("=" * 50)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Run all tests
    tests = [
        ("Firebase Availability", test_firebase_availability),
        ("Firebase Configuration", test_firebase_config),
        ("Firebase Auth API", test_firebase_auth_api),
        ("Local Users", test_local_users),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 DIAGNOSTIC SUMMARY")
    print("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    
    # Recommendations
    print("\n🎯 RECOMMENDATIONS")
    print("=" * 50)
    
    if passed == len(results):
        print("✅ All tests passed! Try these login credentials:")
        print("   - Email: admin@mabs.com, Password: admin123")
        print("   - Email: sales@mabs.com, Password: sales123")
    else:
        print("⚠️  Some tests failed. Here are the solutions:")
        
        if not any(r[1] for r in results if "Firebase" in r[0]):
            print("1. Firebase Issues:")
            print("   - Check your internet connection")
            print("   - Verify Firebase configuration in main.py")
            print("   - Ensure Firebase project is active")
        
        if not any(r[1] for r in results if "Local Users" in r[0]):
            print("2. Local User Issues:")
            print("   - Create test users with the tool below")
        
        print("\n🔧 QUICK FIXES:")
        print("1. Create test users for immediate access")
        print("2. Implement fallback authentication")
        print("3. Check Firebase project settings")
        
        # Offer solutions
        print("\n🛠️  AVAILABLE SOLUTIONS:")
        print("1. Create test users (type 'test')")
        print("2. Create fallback login (type 'fallback')")
        print("3. Exit (type 'exit')")
        
        while True:
            choice = input("\nEnter your choice: ").strip().lower()
            
            if choice == 'test':
                create_test_user()
                break
            elif choice == 'fallback':
                create_fallback_login()
                break
            elif choice == 'exit':
                break
            else:
                print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main()
