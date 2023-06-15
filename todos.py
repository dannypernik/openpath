from app import app
import requests
from todoist_api_python.api import TodoistAPI

### Import Todoist tasks into OnePageCRM
dated_actions = []
new_actions = []
all_task_labels = []
position = 0
crm_response = {"success": 0, "failure": 0}

crm = requests.get("https://app.onepagecrm.com/api/v3/actions?contact_id=646509467241d177b7078a39&per_page=100", auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
todoist = TodoistAPI(app.config['TODOIST_ID'])

for item in crm.json()['data']['actions']:
    if 'date' in item['action']:
        dated_actions.append({
            "id": item['action']['id'],
            "date": item['action']['date'],
            "done": item['action']['done']
        })
    else:
        dated_actions.append({
            "id": item['action']['id'],
            "date": '',
            "done": item['action']['done']
        })

try:
    tasks = todoist.get_tasks(filter='!no date&!recurring')
except Exception as error:
    print(error)

tasks_sorted = sorted(tasks, key=lambda x: x.due.date)

for task in tasks_sorted:
    has_match = False
    for label in task.labels:
        all_task_labels.append({
            "id": task.id,
            "label": label
        })
    for action in dated_actions:
        print(action['id'], task.content, task.labels)
        if action['id'] in task.labels:
            print('action[\'id\'] in task.labels')
            has_match = True
            if action['date'] != task.due.date:
                try:
                    todoist.update_task(task_id=task.id, due_date=action['date'])
                    print('Todoist date updated')
                except:
                    print('Todoist update failed')

            if action['done']:
                todoist.close_task(task_id=task.id)

    if not has_match:
        new_action = {
            "contact_id": "646509467241d177b7078a39",
            "assignee_id": app.config['ONEPAGECRM_ID'],
            "status": "date",
            "text": task.content,
            "date": task.due.date,
            "position": position
        }

        crm_post = requests.post("https://app.onepagecrm.com/api/v3/actions", json=new_action, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW'])).json()

        # Assign CRM id to Todoist task label
        task.labels.append(crm_post['data']['action']['id'])
        todoist.update_task(task_id=task.id, labels=task.labels)

        if crm_post['status'] == 0:
            crm_response['success'] += 1
        else:
            crm_response['failure'] += 1 
        position += 1

if (crm_response['success'] + crm_response['failure']) > 0:
    print('New tasks found:', crm_response['success'], 'successfully created', \
        crm_response['failure'], 'failed.', )
