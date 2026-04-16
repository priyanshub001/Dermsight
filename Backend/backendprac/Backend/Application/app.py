from flask import Flask
from config import Config
from extensions import mongo, bcrypt, jwt

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not app.config.get("MONGO_URI"):
        raise ValueError("MONGO_URI not found. Check your .env file!")

    mongo.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)

    from routes import main
    app.register_blueprint(main)

    return app

app = create_app()

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)