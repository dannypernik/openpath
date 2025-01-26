import requests

def get_act_report():
  url = "https://actgrader.melioratutoringandtestprep.com/api"
  headers = {
      "Content-Type": "multipart/form-data"
  }
  data = {
      "first": "Max",
      "last": "Jones",
      "test_code": "201906"
  }
  files = {
      "file": open("app/static/test/test.jpg", "rb")
  }

  response = requests.post(url, headers=headers, data=data, files=files)

  # Save the response content to a file
  with open("app/static/test/output.zip", "wb") as f:
      f.write(response.content)