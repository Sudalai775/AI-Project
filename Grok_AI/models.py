from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Reminder(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	task = db.Column(db.String(200), nullable=False)
	time_phrase = db.Column(db.String(100), nullable=False)
	created_at = db.Column(db.String(50), nullable=False)
	completed = db.Column(db.Boolean, default=False)
	user_id = db.Column(db.String(100), nullable=True)  # For user-specific data

class CommandHistory(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	command = db.Column(db.String(200), nullable=False)
	timestamp = db.Column(db.String(50), nullable=False)
	user_id = db.Column(db.String(100), nullable=True)

def init_db(app):
	db.init_app(app)
	with app.app_context():
		db.create_all()
