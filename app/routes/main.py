from flask import Blueprint, render_template, request, redirect, session, url_for, flash, current_app

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("main.home"))
    return render_template("login.html")

@bp.route("/home")
def home():
    if not session.get("logged_in"):
        return redirect(url_for("main.index"))
    return render_template("home.html")

@bp.route("/login", methods=["POST"])
def login():
    pw = request.form.get("password", "")
    if pw == current_app.config.get("APP_PASSWORD"):
        session["logged_in"] = True
        return redirect(url_for("main.home"))
    flash("Invalid password")
    return redirect(url_for("main.index"))

@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.index"))
