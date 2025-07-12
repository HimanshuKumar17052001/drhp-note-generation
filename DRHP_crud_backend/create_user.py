import sys
import os
from pathlib import Path

current_dir = Path(__file__).parent
project_root = str(current_dir)
sys.path.append(project_root)

import random, string
from mongoengine import connect
from app.models.schemas import User
import bcrypt
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

def create_user(name: Optional[str], username: str, email: str, password: str) -> User:
  
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    # Check if username or email already exists
    if User.objects(username=username).first():
        user = User.objects(username=username).first()
        user.update(set__password=hashed_password)
        raise Exception(f"Username already exists. Password was updated to {password}")
    
    if User.objects(email=email).first():
        user = User.objects(email=email).first()
        user.update(set__password=hashed_password)
        raise Exception(f"Email already exists. Password was updated to {password}")
    
    # Hash the password
    # hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    # Create new user
    user = User(
        name=name,
        username=username,
        email=email,
        password=hashed_password
    )
    
    # Save user to database
    user.save()
    
    return user

# Example usage:
if __name__ == "__main__":
    try:
        # Connect to MongoDB (adjust connection string as needed)
        print(os.getenv('MONGO_URI'))
        connect(
            db=os.getenv('MONGO_DB'),
            host=os.getenv('MONGO_URI')
        )
        
        users = ["prathmesh.goswami@bseindia.com", "aniruddha.kulkarni@bseindia.com"]
        # Create a new user
        for user in users:
           pwd = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
           new_user = create_user(
               name="",
               username=user.split("@")[0],
               email=user,
               password=pwd
           )
           print(f"User created successfully with id: {new_user.id}: {new_user.email} and {pwd}")
        
    except Exception as e:
        print(f"Error creating user: {str(e)}") 
