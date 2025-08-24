import unittest
from app import app, db, Reminder, CommandHistory

class TestApp(unittest.TestCase):
	def setUp(self):
		app.config['TESTING'] = True
		app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
		self.app = app.test_client()
		with app.app_context():
			db.create_all()

	def tearDown(self):
		with app.app_context():
			db.drop_all()

	def test_reminder_creation(self):
		response = self.app.post('/api/process_command', json={'command': 'Remind me to study at 7 PM'})
		self.assertEqual(response.status_code, 200)
		data = response.get_json()
		self.assertEqual(data['status'], 'success')
		self.assertIn('Reminder Created Successfully', data['response'])

	def test_weather_command(self):
		response = self.app.post('/api/process_command', json={'command': 'Weather in Chennai'})
		self.assertEqual(response.status_code, 200)
		data = response.get_json()
		self.assertEqual(data['status'], 'success')
		self.assertIn('Chennai', data['response'])

if __name__ == '__main__':
	unittest.main()
