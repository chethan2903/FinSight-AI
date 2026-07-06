import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "marketmind.settings")
django.setup()

from django.contrib.auth.models import User
from market.utils.rag_assistant import answer_question

try:
    user = User.objects.get(username="admin")
    print("[*] Testing 'What are my holdings?'")
    ans1 = answer_question(user, "What are my holdings?")
    print("REPLY 1:", ans1.replace("₹", "INR"))
    
    print("\n[*] Testing 'What is the news for Apple?'")
    ans2 = answer_question(user, "What is the news for Apple?")
    print("REPLY 2:", ans2.replace("₹", "INR"))
except Exception as e:
    print("[ERROR] Exception occurred during assistant test:", e)
    import traceback
    traceback.print_exc()
