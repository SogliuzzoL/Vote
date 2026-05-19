import os
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
# Prefer a secret from env, fall back to a random one for dev
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///votes.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Discord / admin config
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_API_BASE_URL = "https://discord.com/api"
ADMIN_DISCORD_IDS = [
    i.strip() for i in os.getenv("ADMIN_DISCORD_IDS", "").split(",") if i.strip()
]


# --- MODÈLES DE BASE DE DONNÉES ---


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discord_id = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(100), nullable=False)


class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    vote_type = db.Column(
        db.String(50), default="rating", nullable=False
    )  # rating, single, multiple
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    options = db.relationship(
        "Option",
        back_populates="poll",
        cascade="all, delete-orphan",
        order_by="Option.id",
    )


class Option(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("poll.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)

    poll = db.relationship("Poll", back_populates="options")


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    poll_id = db.Column(db.Integer, db.ForeignKey("poll.id"), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey("option.id"), nullable=True)
    score = db.Column(db.Integer, nullable=True)  # pour les votes en "rating"


# Paramètres globaux simples (optionnel)
class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), default="🎮 Vote", nullable=False)


def get_settings():
    s = Settings.query.first()
    if not s:
        s = Settings(title="🎮 Vote")
        db.session.add(s)
        db.session.commit()
    return s


# --- ROUTES ---


@app.route("/")
def index():
    settings = get_settings()
    polls = Poll.query.filter_by(active=True).order_by(Poll.created_at.desc()).all()
    login_url = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify"
    user = None
    if "user_id" in session:
        user = User.query.get(session["user_id"])
    return render_template(
        "index.html", login_url=login_url, settings=settings, polls=polls, user=user
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if "user_id" not in session:
        return redirect(url_for("index"))

    user = User.query.get(session["user_id"])
    if str(user.discord_id) not in ADMIN_DISCORD_IDS:
        return "Accès refusé, tu n'es pas administrateur.", 403

    settings = get_settings()

    # Allow editing global settings from admin dashboard
    if request.method == "POST":
        settings.title = request.form.get("title")
        db.session.commit()
        flash("Paramètres enregistrés.")
        return redirect(url_for("admin"))

    polls = Poll.query.order_by(Poll.created_at.desc()).all()
    return render_template("admin.html", settings=settings, user=user, polls=polls)


@app.route("/admin/new", methods=["GET", "POST"])
def admin_new():
    if "user_id" not in session:
        return redirect(url_for("index"))
    user = User.query.get(session["user_id"])
    if str(user.discord_id) not in ADMIN_DISCORD_IDS:
        return "Accès refusé, tu n'es pas administrateur.", 403

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        vote_type = request.form.get("vote_type")
        active = True if request.form.get("active") == "on" else False

        poll = Poll(
            title=title or "Untitled poll",
            description=description,
            vote_type=vote_type,
            active=active,
        )
        db.session.add(poll)
        db.session.commit()

        # new options
        new_options = request.form.getlist("new_option[]")
        for name in new_options:
            if name and name.strip():
                db.session.add(Option(poll_id=poll.id, name=name.strip()))
        db.session.commit()

        flash("Nouveau vote créé.")
        return redirect(url_for("admin"))

    return render_template("admin_edit.html", poll=None, user=user)


@app.route("/admin/<int:poll_id>/edit", methods=["GET", "POST"])
def admin_edit(poll_id):
    if "user_id" not in session:
        return redirect(url_for("index"))
    user = User.query.get(session["user_id"])
    if str(user.discord_id) not in ADMIN_DISCORD_IDS:
        return "Accès refusé, tu n'es pas administrateur.", 403

    poll = Poll.query.get_or_404(poll_id)

    if request.method == "POST":
        poll.title = request.form.get("title")
        poll.description = request.form.get("description")
        poll.vote_type = request.form.get("vote_type")
        poll.active = True if request.form.get("active") == "on" else False

        # update existing options
        for opt in list(poll.options):
            name = request.form.get(f"option_name_{opt.id}")
            if request.form.get(f"delete_option_{opt.id}") == "on":
                db.session.delete(opt)
            else:
                if name and name.strip():
                    opt.name = name.strip()
                else:
                    db.session.delete(opt)

        # add new options
        new_options = request.form.getlist("new_option[]")
        for name in new_options:
            if name and name.strip():
                db.session.add(Option(poll_id=poll.id, name=name.strip()))

        db.session.commit()
        flash("Vote mis à jour.")
        return redirect(url_for("admin"))

    return render_template("admin_edit.html", poll=poll, user=user)


@app.route("/admin/<int:poll_id>/delete", methods=["POST"])
def admin_delete(poll_id):
    if "user_id" not in session:
        return redirect(url_for("index"))
    user = User.query.get(session["user_id"])
    if str(user.discord_id) not in ADMIN_DISCORD_IDS:
        return "Accès refusé, tu n'es pas administrateur.", 403

    poll = Poll.query.get_or_404(poll_id)
    db.session.delete(poll)
    db.session.commit()
    flash("Vote supprimé.")
    return redirect(url_for("admin"))


@app.route("/vote/<int:poll_id>", methods=["GET", "POST"])
def vote_poll(poll_id):
    if "user_id" not in session:
        return redirect(url_for("index"))

    user = User.query.get(session["user_id"])
    poll = Poll.query.get_or_404(poll_id)

    # check if user already voted on this poll
    has_voted = Vote.query.filter_by(user_id=user.id, poll_id=poll.id).first()
    if has_voted:
        return redirect(url_for("results", poll_id=poll.id))

    options = poll.options

    if request.method == "POST":
        if poll.vote_type == "rating":
            for opt in options:
                score = request.form.get(f"option_{opt.id}")
                if score:
                    db.session.add(
                        Vote(
                            user_id=user.id,
                            poll_id=poll.id,
                            option_id=opt.id,
                            score=int(score),
                        )
                    )

        elif poll.vote_type == "single":
            option_id = request.form.get("option_choice")
            if option_id:
                db.session.add(
                    Vote(
                        user_id=user.id,
                        poll_id=poll.id,
                        option_id=int(option_id),
                        score=1,
                    )
                )

        elif poll.vote_type == "multiple":
            option_ids = request.form.getlist("option_choice")
            for oid in option_ids:
                db.session.add(
                    Vote(user_id=user.id, poll_id=poll.id, option_id=int(oid), score=1)
                )

        db.session.commit()
        return redirect(url_for("results", poll_id=poll.id))

    return render_template(
        "vote.html",
        user=user,
        poll=poll,
        options=options,
        editing=False,
        user_votes=None,
    )


@app.route("/vote/<int:poll_id>/edit", methods=["GET", "POST"])
def edit_vote(poll_id):
    """Permet à un utilisateur de modifier son vote existant.

    On supprime d'abord les votes existants pour cet utilisateur et ce sondage,
    puis on enregistre les nouveaux en fonction du formulaire.
    """
    if "user_id" not in session:
        return redirect(url_for("index"))

    user = User.query.get(session["user_id"])
    poll = Poll.query.get_or_404(poll_id)
    options = poll.options

    existing_votes = Vote.query.filter_by(user_id=user.id, poll_id=poll.id).all()

    if request.method == "POST":
        # supprimer les anciens votes
        for v in existing_votes:
            db.session.delete(v)
        db.session.commit()

        # recréer en fonction du formulaire
        if poll.vote_type == "rating":
            for opt in options:
                score = request.form.get(f"option_{opt.id}")
                if score:
                    db.session.add(
                        Vote(
                            user_id=user.id,
                            poll_id=poll.id,
                            option_id=opt.id,
                            score=int(score),
                        )
                    )

        elif poll.vote_type == "single":
            option_id = request.form.get("option_choice")
            if option_id:
                db.session.add(
                    Vote(
                        user_id=user.id,
                        poll_id=poll.id,
                        option_id=int(option_id),
                        score=1,
                    )
                )

        elif poll.vote_type == "multiple":
            option_ids = request.form.getlist("option_choice")
            for oid in option_ids:
                db.session.add(
                    Vote(user_id=user.id, poll_id=poll.id, option_id=int(oid), score=1)
                )

        db.session.commit()
        flash("Vote modifié.")
        return redirect(url_for("results", poll_id=poll.id))

    # construire une structure pratique pour pré-remplir le formulaire
    if poll.vote_type == "rating":
        user_votes = {v.option_id: v.score for v in existing_votes}
    else:
        user_votes = {v.option_id for v in existing_votes}

    return render_template(
        "vote.html",
        user=user,
        poll=poll,
        options=options,
        editing=True,
        user_votes=user_votes,
    )


@app.route("/results/<int:poll_id>")
def results(poll_id):
    poll = Poll.query.get_or_404(poll_id)
    settings = get_settings()

    # connaître l'utilisateur courant pour proposer la modification si besoin
    user = None
    has_voted = False
    if "user_id" in session:
        user = User.query.get(session["user_id"])
        if Vote.query.filter_by(user_id=user.id, poll_id=poll.id).first():
            has_voted = True

    resultats_finaux = []
    for opt in poll.options:
        votes = Vote.query.filter_by(poll_id=poll.id, option_id=opt.id).all()
        if poll.vote_type == "rating":
            moyenne = sum(v.score for v in votes) / len(votes) if votes else 0
            resultats_finaux.append(
                {
                    "nom": opt.name,
                    "affichage": f"{round(moyenne, 2)}/5",
                    "valeur_tri": moyenne,
                    "total_votes": len(votes),
                }
            )
        else:
            count = len(votes)
            resultats_finaux.append(
                {
                    "nom": opt.name,
                    "affichage": f"{count} votes",
                    "valeur_tri": count,
                    "total_votes": count,
                }
            )

    resultats_finaux = sorted(
        resultats_finaux, key=lambda x: x["valeur_tri"], reverse=True
    )
    return render_template(
        "results.html",
        resultats=resultats_finaux,
        poll=poll,
        settings=settings,
        user=user,
        has_voted=has_voted,
    )


@app.route("/callback")
def callback():
    code = request.args.get("code")
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(
        f"{DISCORD_API_BASE_URL}/oauth2/token", data=data, headers=headers
    )
    r.raise_for_status()
    token = r.json().get("access_token")

    user_r = requests.get(
        f"{DISCORD_API_BASE_URL}/users/@me",
        headers={"Authorization": f"Bearer {token}"},
    )
    user_data = user_r.json()

    user = User.query.filter_by(discord_id=user_data["id"]).first()
    if not user:
        user = User(discord_id=user_data["id"], username=user_data["username"])
        db.session.add(user)
        db.session.commit()

    session["user_id"] = user.id
    return redirect(url_for("index"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        # Si aucun sondage n'existe, crée un exemple
        if not Poll.query.first():
            p = Poll(
                title="Exemple : Quel modpack ?",
                description="Vote d'exemple",
                vote_type="rating",
                active=True,
            )
            db.session.add(p)
            db.session.commit()
            db.session.add_all(
                [
                    Option(poll_id=p.id, name="Create: Astral"),
                    Option(poll_id=p.id, name="All the Mods 9"),
                ]
            )
            db.session.commit()
    app.run(debug=True, host="0.0.0.0")
