import os
import tempfile

# Test dùng DB tạm, không đụng var/brief.db thật.
os.environ["BRIEF_DB"] = os.path.join(tempfile.mkdtemp(prefix="brief-test-"), "test.db")
