import os
import operator
import bcrypt
import random
import datetime, time
from functools import wraps
from flask import Flask, render_template, send_file, request, redirect, url_for
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_login import UserMixin, current_user, login_user, LoginManager, login_required, logout_user
from flask_talisman import Talisman
from sqlalchemy.orm import relationship
from wtforms import StringField, TextAreaField, SelectField, SubmitField, PasswordField
from wtforms.fields.simple import TextField
from wtforms.validators import DataRequired, InputRequired, Length, ValidationError
from urllib.parse import quote
import bleach

# Specific for this project
from export import export_catalogus_to_word, export_session_to_word 

def setKey(key, default):
    try:
        return os.environ[key]
    except KeyError:
        print(f'*** Missing envioronmental variable {key}, using {default} as default.')
        return default

db_config = {
    "user": setKey('SQL_USER', 'root'),
    "password": setKey('SQL_PASSWORD', 'root'),
    "host": setKey('SQL_HOST', 'localhost'),
    "database": setKey('SQL_DB', 'interventie'),
    "port": setKey('SQL_PORT', '1433'),
    "server_type": setKey('SERVER_TYPE', 'mssql+pyodbc'),
    "force_https": setKey('FORCE_HTTPS', 'TRUE')
}

MAINTAINER = setKey('MAINTAINER', "None specified")
MAINTAINER_EMAIL = setKey('MAINTAINER_EMAIL', "None specified")

connection_string = f'{db_config["server_type"]}://{quote(db_config["user"])}:{quote(db_config["password"])}@{db_config["host"]}:{db_config["port"]}/{db_config["database"]}{"?driver=ODBC+Driver+17+for+SQL+Server" if db_config["server_type"]=="mssql+pyodbc" else ""}'
print (connection_string)

app = Flask(__name__)
if db_config['force_https'] == "TRUE":
    Talisman(app, content_security_policy=None)
        

app.config['SECRET_KEY'] = setKey('SECRET_KEY', 'NOKEYSPECIFIED')
app.config['SQLALCHEMY_DATABASE_URI'] = connection_string
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 60,
    'pool_pre_ping': True
}

db = SQLAlchemy(app)

bcrypt=Bcrypt(app)
bleach.ALLOWED_TAGS.append('br')

# Methoden voor het bepalen van de prioriteit op basis van plustags en mintags
DIFFERENCE = 0
EXCLUDED = 1
WEIGH_DOWN = 2
# Instellingen
METHOD = EXCLUDED    # De gehanteerde methode voor het bepalen van de prioriteit van de instrumenten
MARGIN = 1                  # Als de score van een instrument minder dan de MARGIN verschilt met de topprioriteit, geef dan ook de topprioriteit
# Prioriteiten, correspondeert met CSS
PRIO_HI = 2
PRIO_MID = 1
PRIO_LO = 0


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), nullable=False, unique=True)
    password = db.Column(db.String(80), nullable=False)
    role = db.Column(db.Integer, nullable=False)
    # 1: admin
    # 2: normale gebruiker
    active_session = db.Column(db.Integer)

class Instrument(db.Model):
    __tablename__ = 'instrumenten'
    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(100), nullable=False)
    intro = db.Column(db.Text, nullable=False) # Dikgedrukt, bovenaan.
    beschrijving = db.Column(db.Text, nullable=False)
    afwegingen = db.Column(db.Text, nullable=False)
    voorbeelden  = db.Column(db.Text, nullable=False)
    links = db.Column(db.Text)
    eigenaar = db.Column(db.String(100), nullable=False)
    eigenaar_email = db.Column(db.String(100), nullable=False)
    tags = relationship('Tag', secondary="associations_IT")
    extags = relationship('Tag', secondary="associations_XIT")

    def __repr__(self):
        return '<Instrument %r>' % self.naam

class Tag(db.Model):
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(100), nullable=False)
    def __repr__(self):
        return '<Tag %r>' % self.naam

# Tabel met relaties tussen instrumenten en plustags
associations_IT = db.Table('associations_IT',
                            db.Column('id', db.Integer, primary_key=True),
                            db.Column('instrument_id', db.Integer, db.ForeignKey('instrumenten.id')),
                            db.Column('tag_id', db.Integer, db.ForeignKey('tags.id')))

# Tabel met associaties tussen instrumenten en mintags
associations_XIT = db.Table('associations_XIT',
                            db.Column('id', db.Integer, primary_key=True),
                            db.Column('instrument_id', db.Integer, db.ForeignKey('instrumenten.id')),
                            db.Column('tag_id', db.Integer, db.ForeignKey('tags.id')))

class Optie(db.Model):
    __tablename__ = 'opties'
    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(200), nullable=False)
    vraag_id = db.Column(db.Integer, db.ForeignKey('vragen.id'), nullable=False)
    tags = relationship('Tag', secondary="associations_TO")
    
    def __repr__(self):
        return '<Optie %r>' % self.naam

# Associaties tussen opties en tags
associations_TO = db.Table('associations_TO',
                            db.Column('id', db.Integer, primary_key=True),
                            db.Column('optie_id', db.Integer, db.ForeignKey('opties.id')),
                            db.Column('tag_id', db.Integer, db.ForeignKey('tags.id')))

class Vraag(db.Model):
    __tablename__ = 'vragen'
    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(200), nullable=False)
    categorie_id = db.Column(db.Integer, db.ForeignKey('categorieen.id'), nullable=False)
    opties = db.relationship('Optie', backref='optie')
    multiselect = db.Column(db.Boolean, nullable=False)

    def __repr__(self):
        return '<Vraag %r>' % self.naam  

class Categorie(db.Model):
    __tablename__ = 'categorieen'
    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(100), nullable=False)
    vragen = db.relationship('Vraag', backref='vraag')

    def __repr__(self):
        return '<Categorie %r>' % self.naam

class Werksessie(db.Model):
    __tablename__ = 'werksessies'
    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(100), nullable=False)
    auteurs = db.Column(db.String(500), nullable=True)
    datum = db.Column(db.String(100), nullable=True)
    probleemstelling = db.Column(db.String(500), nullable=True)
    conclusie = db.Column(db.String(2000), nullable=True)
    owner = db.Column(db.Integer)
    showinstruments = db.Column(db.Boolean, nullable=True, default=True)

    geselecteerde_opties = relationship('Optie', secondary="associations_OS")
    motivaties = relationship('Motivaties', secondary='associations_Ws_Mot')

    def __repr__(self):
        return '<Sessie %r>' % self.naam


class Motivaties(db.Model):
    __tablename__ = 'motivaties'
    id = db.Column(db.Integer, primary_key=True)
    motivatie = db.Column('motivatie', db.String(500))
    vraag = db.Column('vraag_id', db.Integer, nullable=False)

    def __repr__(self):
        return '<Motivatie %r>' % self.motivatie

# Tabel met de antwoorden op de vragen bij de specifieke werksessie
associations_OS = db.Table('associations_OS',
                            db.Column('id', db.Integer, primary_key=True),
                            db.Column('optie_id', db.Integer, db.ForeignKey('opties.id')),
                            db.Column('werksessie_id', db.Integer, db.ForeignKey('werksessies.id'))
                            )

# Tabel met de open antwoorden per vraag bij de specifieke werksessie
associations_Ws_Mot = db.Table('associations_Ws_Mot',
                            db.Column('id', db.Integer, primary_key=True),
                            db.Column('werksessie_id', db.Integer, db.ForeignKey('werksessies.id')),
                            db.Column('motivatie_id', db.Integer, db.ForeignKey('motivaties.id'))
                            )

class RegisterForm(FlaskForm):
    username = StringField(validators=[InputRequired(), Length(min=4, max=20)], render_kw={"placeholder": "Nieuwe naam"})
    password = PasswordField(validators=[InputRequired(), Length(min=4, max=20)], render_kw={"placeholder": "Wachtwoord"})
    submit = SubmitField("Maak nieuwe gebruiker")

    def validate_username(self, username):
        existing_user_username = User.query.filter_by(username=username.data).first()
        if existing_user_username:
            raise ValidationError("Gebruikersnaam bestaat al. Kies een andere gebruikersnaam.")

class PasswordForm(FlaskForm):
    password = PasswordField(validators=[InputRequired(), Length(min=4, max=20)], render_kw={"placeholder": "Nieuw wachtwoord"})
    submit = SubmitField("Verander wachtwoord")

class LoginForm(FlaskForm):
    username = StringField(validators=[InputRequired(), Length(min=4, max=20)], render_kw={"placeholder": "Gebruikersnaam"})
    password = PasswordField(validators=[Length(min=4, max=20)], render_kw={"placeholder": "Wachtwoord"})
    submit = SubmitField("Login")

class WerksessieForm(FlaskForm):   
    naam = StringField('Casus', validators=[DataRequired(), Length(max=100)])
    auteurs = TextAreaField('Deelnemers',  validators=[Length(max=500)])
    datum = StringField('Datum',  validators=[Length(max=100)])
    probleemstelling = TextAreaField('Centrale probleemstelling', validators=[Length(max=500)] )
    conclusie = TextAreaField('Definitieve overwegingen instrumentselectie', validators=[Length(max=2000)])
    submit = SubmitField('Opslaan')

class InstrumentForm(FlaskForm):   
    naam = StringField('Instrumentnaam', validators=[DataRequired()])
    intro = TextAreaField('Koptekst', validators=[DataRequired()])
    beschrijving = TextAreaField('Beschrijving', validators=[DataRequired()])
    afwegingen = TextAreaField('Afwegingen', validators=[DataRequired()])
    voorbeelden = TextAreaField('Voorbeelden')
    links = TextAreaField('Links naar documentatie')
    eigenaar = StringField('Eigenaar')
    eigenaar_email = StringField('E-mail')
    submit = SubmitField('Opslaan')

class CategorieForm(FlaskForm):
    vraag = TextField('Categorie', validators=[DataRequired()])

class VraagForm(FlaskForm):
    categorie = SelectField('Vraagcategorie', validators=[DataRequired()])
    vraag = TextField('Vraag', validators=[DataRequired()])

class OptieForm(FlaskForm):
    vraag = SelectField('Vraag', validators=[DataRequired()])
    optie = TextField('Optie', validators=[DataRequired()])
    tags = relationship('Tag', secondary="associations_TO")

def get_instruments(alle_instrumenten, werksessie=None):
    """Geeft een lijst terug van alle instrumenten. Deze lijst is gesorteerd. Het sorteren is geimplementeerd in een aparte functie."""
    if werksessie == None:
        # Dit kan niet gebeuren
        pass

    instrument_met_alle_tags = []    
    tags_in_scope = []
    for optie in Optie.query.all():
        if optie in werksessie.geselecteerde_opties:
            tags_in_scope.extend(optie.tags)
    # Dit wordt een lijst van alle instrumenten met het aantal tags dat actief is in de werksessie
    for instrument in alle_instrumenten:
        tags = []
        extags = []
        for tag in instrument.tags:
            if tag in tags_in_scope:
                tags.append(tag)
        for tag in instrument.extags:
            if tag in tags_in_scope:
                extags.append(tag)

        instrument_met_alle_tags.append([instrument, tags, extags])
    instrumenten_sorted = prioritize_instruments(instrument_met_alle_tags)
    return instrumenten_sorted

def commit_to_database_success(): 
    success = False
    err = None
    try: 
        db.session.commit()
        success=True
    except Exception as err:
        print(f'Exception {err}')
        db.session.rollback()
    finally: 
        pass
    return success

def prioritize_instruments(instrument_met_alle_tags):
    """Deze functie dient om de lijst te filteren en te sorteren. Omdat ik nog niet precies weet wat de beste methode gaat zijn heb ik
    de methode nog flexibel ingevuld als extra argument."""
    prioritized_list = []
    max_priority = 0
    
    for instrument in instrument_met_alle_tags:
        # Vaststellen en berekenen van plustags en mintags
        tag_hits = len(instrument[1])
        extag_hits = len(instrument[2])

        if METHOD == DIFFERENCE: # Sortering en kleuring op basis van aantal plustags min het aantal mintags.
            priority = tag_hits - extag_hits
        if METHOD == EXCLUDED: # Sortering waarbij een enkele actieve mintag het instrument helemaal excludeert.
            priority = tag_hits * (extag_hits == 0)
        if METHOD == WEIGH_DOWN: # Sortering waarbij mintags zwaarder tellen dan plustags.
            priority = tag_hits - 2 * extag_hits
        priority_class = 0
        prioritized_list.append([instrument[0], tag_hits, instrument[1], extag_hits, instrument[2], priority, priority_class])
        max_priority = max(priority, max_priority) # Boekhouding om de hoogste prioriteitsscore later te kunnen gebruiken            
    for instrument in prioritized_list:
        # Bepalen van de prioriteitsklassen
        if instrument[5] == 0:
            instrument[6] = PRIO_LO
        elif instrument[5] == max_priority:
            instrument[6] = PRIO_HI
        elif instrument[5] >= (max_priority - MARGIN):
            instrument[6] = PRIO_HI
        elif instrument[5] > 0:
            instrument[6] = PRIO_MID
        else:
            instrument[6] = PRIO_LO

    return sorted(prioritized_list, key=operator.itemgetter(5), reverse=True)

def Verander_werksessie(sessie_id):
    if current_user.role == 1:
        # Voor admins kan gewoon worden geselecteerd.
        ws = Werksessie.query.filter_by(id=sessie_id).first()
        if ws is None:
            # Niets gevonden, dan maar gewoon de eerstvolgende sessie activeren.
            ws = Werksessie.query.first()
    else:
        # Voor gewone gebruikers moeten we op zoek naar een sessie waarvan ze owner zijn.
        ws = Werksessie.query.filter_by(id=sessie_id, owner=current_user.id).first()
        if ws is None:
            # Niets gevonden, dan maar de eerstvolgende sessie van de gebruiker activeren.
            ws = Werksessie.query.filter_by(owner=current_user.id).first()
    if ws is None:
        sessie_id = None
    user_to_update = User.query.filter_by(id=current_user.id).first()
    user_to_update.active_session = sessie_id
    return commit_to_database_success()

def Beperk_werksessies(werksessies):
    """Als de gebruiker geen admin is, dan beperkt deze functie de werksessies in de lijst tot die sessies die de gebruiker heweft gemaakt."""
    if current_user.role == 1:
        return werksessies
    else:
        return_list = []
        for ws in werksessies:
            if ws.owner == current_user.id:
                return_list.append(ws)
        return return_list

def werksessie_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.active_session is None:
            return render_template('error.html', melding='Geen werksessie geselecteerd', tekst='Kies eerst een werksessie. Als er geen werksessies beschikbaar zijn, maak dan een nieuwe aan op de introductiepagina')
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.role == 1:
            return render_template('error.html', melding='Onvoldoende rechten', tekst='Alleen administrators mogen deze handeling uitvoeren.')
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            if bcrypt.check_password_hash(user.password, form.password.data):
                login_user(user)
                Verander_werksessie(user.active_session)
                return redirect(url_for('intro'))
    return render_template('login.html', form=form,
                        maintainer=MAINTAINER, 
                        maintainer_email=MAINTAINER_EMAIL)

@app.route('/info')
def info():
    db_config_cleaned = db_config
    db_config_cleaned["password"] = "***"
    db_config_cleaned.update({"password":"***",
                        "pool size": db.engine.pool.size()})
    return render_template('info.html',
                           maintainer=MAINTAINER, 
                           maintainer_email=MAINTAINER_EMAIL,
                           db_config=db_config_cleaned)

@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/make_admin/<int:user_id>')
@admin_required
def make_admin(user_id):
    """Maakt van deze gebruiker een administrator."""
    if current_user.role == 1:
        User.query.filter_by(id=user_id).first().role = 1
        if commit_to_database_success():
            return redirect(url_for('account'))
        else:
            return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')

        return redirect(url_for('account'))

@app.route('/make_user/<int:user_id>')
@admin_required
def make_user(user_id):
    """Maakt van deze gebruiker een gewone gebruiker (geen admin)."""
    if current_user.role == 1 and user_id > 2: # User 0 en 1 moeten admin blijven.
        User.query.filter_by(id=user_id).first().role = 0
        if commit_to_database_success():
            return redirect(url_for('account'))
        else:
            return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')

    return redirect(url_for('account'))

@app.route('/delete_user/<int:user_id>')
@admin_required
def delete_user(user_id):
    if current_user.role == 1:
        user_to_delete = User.query.filter_by(id=user_id).first()
        if user_to_delete.role != 1:
            db.session.delete(user_to_delete)
            if commit_to_database_success():
                return redirect(url_for('account'))
            else:
                return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')
    return redirect(url_for('account'))

@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    formRegister = RegisterForm()
    formPassword = PasswordForm()
    if request.method == 'POST':
        if formRegister.submit.data:
            if formRegister.validate_on_submit():
                hashed_password = bcrypt.generate_password_hash(formRegister.password.data)
                new_user = User(username=formRegister.username.data, password=hashed_password, role=0)
                # role 1 is de admin-rol. Standaard zijn alle nieuwe accounts gewone users.
                # Bestaande administrators kunnen een nieuwe gebruiker admin maken.
                db.session.add(new_user)
                if commit_to_database_success():
                    return redirect(url_for('account'))
                else:
                    return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')

        if formPassword.submit.data:
            if formPassword.validate_on_submit():
                user_to_update = User.query.filter_by(id=current_user.id).first()
                hashed_password = bcrypt.generate_password_hash(formPassword.password.data)
                user_to_update.password = hashed_password
                # Schrijf het wachtwoord naar de database
                if commit_to_database_success():
                    return redirect(url_for('account'))
                else:
                    return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')
    
    return render_template('account.html', 
                            formRegister=formRegister, 
                            formPassword=formPassword, 
                            users=User.query.order_by(User.username))


@app.route('/reset_user_password/<int:user_id>')
@admin_required
def resetUserPassword(user_id):
    new_password = ''.join((random.choice('QWERTYUIOPASDFGHJKLZXCVBNM1234567890') for i in range(8)))
    hashed_password = bcrypt.generate_password_hash(new_password)
    user_to_update = User.query.filter_by(id=user_id).first()
    user_to_update.password = hashed_password

    if commit_to_database_success():
        return render_template('reset_user_password.html', password=new_password, username=user_to_update.username)
    else:
        return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')


@app.route('/')
@login_required
def intro():
    huidige_werksessie = Werksessie.query.get(current_user.active_session)
    alle_werksessies = Beperk_werksessies(Werksessie.query.order_by(Werksessie.id).all())
    return render_template('intro.html', 
                           werksessie=huidige_werksessie,
                           maintainer=MAINTAINER, 
                           maintainer_email=MAINTAINER_EMAIL,
                           werksessies=alle_werksessies,
                           actieve_werksessie=current_user.active_session)

@app.route('/maintenance')
@admin_required
def maintenance():
    for optie in Optie.query.order_by(Optie.id).all():
        if optie.vraag_id==None:
            Optie.query.filter_by(id=optie.id).delete()
    
    #Onderstaande onderhoud hoeft denk ik niet, want vragen hoeven niet nooodzakelijk tot een categorie te behoren.
    for vraag in Vraag.query.order_by(Vraag.id).all():
        if vraag.categorie_id==None:
            Vraag.query.filter_by(id=vraag.id).delete()

    werksessie = Werksessie.query.get_or_404(current_user.active_session)
    alle_instrumenten=Instrument.query.order_by(Instrument.naam).all()


    if commit_to_database_success():
        return render_template('questionnaire.html',
                           werksessie=werksessie,
                           instrumenten=get_instruments(alle_instrumenten, werksessie),
                           categorieen=Categorie.query.order_by(Categorie.naam).all())
    else:
        return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')

@app.route('/start_fresh')  # Met deze functie wordt de huidige werksessie gewist: alle gegeven antwoorden worden weer open gesteld.
@login_required
def start_fresh():
    try:
        werksessie = Werksessie.query.get_or_404(current_user.active_session)
    except:
        werksessie = Werksessie(naam="Start")
        db.session.add(werksessie)
    # Opties wissen    
    werksessie.geselecteerde_opties = []

    # Open antwoorden wissen
    for motivatie in werksessie.motivaties:
        werksessie.motivaties.remove(motivatie)
        db.session.delete(motivatie)

    alle_instrumenten=Instrument.query.order_by(Instrument.naam).all()
    if commit_to_database_success():
        return render_template('questionnaire.html',
                           werksessie=werksessie,
                           instrumenten=get_instruments(alle_instrumenten, werksessie),
                           categorieen=Categorie.query.order_by(Categorie.naam).all())
    else:
        return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')
    

@app.route('/change_method/<int:new_method>')
@admin_required
def change_sorting_method(new_method):
    METHOD = new_method
    return f'Huidige methode van selectie: {str(METHOD)}.'

@app.route('/add_session')
@login_required
def add_session():
    werksessie = Werksessie(naam=f"Nieuwe werksessie ({current_user.username}, {datetime.date.today()})", 
                            datum=datetime.date.today(), 
                            auteurs=current_user.username, 
                            probleemstelling='',
                            conclusie='',
                            owner=current_user.id)
    
    db.session.add(werksessie)
    if commit_to_database_success():
        Verander_werksessie(werksessie.id)
        return redirect(url_for('case'))
    else:
        return render_template('error.html', melding='Database', tekst='Probleem met schrijven naar de database')

@app.route('/case', methods=['GET', 'POST'])
@login_required
@werksessie_required
def case():
    huidige_werksessie = Werksessie.query.get_or_404(current_user.active_session)
    alle_werksessies = Beperk_werksessies(Werksessie.query.order_by(Werksessie.id).all())
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    alle_categorieen = Categorie.query.order_by(Categorie.naam).all()
    form = WerksessieForm(naam=huidige_werksessie.naam, 
                          auteurs=huidige_werksessie.auteurs,
                          datum=huidige_werksessie.datum,
                          probleemstelling=huidige_werksessie.probleemstelling)

    if form.validate_on_submit():
        huidige_werksessie.naam = request.form['naam']
        huidige_werksessie.auteurs = request.form['auteurs']
        huidige_werksessie.datum = request.form['datum']
        huidige_werksessie.probleemstelling = request.form['probleemstelling']

        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan wijzigingen niet opslaan', tekst='Het opslaan van wijzigingen aan de werksessie is mislukt. Waarschijnlijk bevat het veld teveel tekens.')    
    elif form.is_submitted():
        return render_template('error.html', melding='Kan wijzigingen niet opslaan', tekst=form.errors)    
    return render_template('case.html',
                                form=form,
                                werksessie=huidige_werksessie, 
                                werksessies=alle_werksessies,
                                instrumenten=alle_instrumenten, 
                                categorieen=alle_categorieen,
                                actieve_werksessie=current_user.active_session)

@app.route('/case/<int:werksessie_id>/showinstruments/<int:enabled>')
@login_required
def toggle_showinstruments(werksessie_id, enabled=0):
    werksessie_to_update = Werksessie.query.get_or_404(werksessie_id)
    if enabled==1:
        werksessie_to_update.showinstruments = True
    else:
        werksessie_to_update.showinstruments = False
    
    if commit_to_database_success():
        return redirect(url_for('questionnaire'))
    else:
        return render_template('error.html', melding='Kan optie niet wijzigen', tekst='Het wijzigen van de optie is mislukt. Misschien is er een probleem met de database?')
       

@app.route('/activate_session/<int:sessie_id>')
@login_required
def activate_session(sessie_id):
    Verander_werksessie(sessie_id)
    return redirect(url_for('case'))   

@app.route('/delete_session/<int:sessie_id>')
# De gebruiker moet wel óf admin óf eigenaar van de werksessie zijn.
@login_required
@werksessie_required
def delete_session(sessie_id):
    werksessie_to_delete = Werksessie.query.get_or_404(current_user.active_session)
    if (werksessie_to_delete.owner != current_user.id) and (current_user.role != 1):
        return render_template('error.html', melding='Mag de werksessie niet verwijderen', tekst='Het verwijderen van de werksessie is mislukt. Alleen de eigenaar of een administrator mag deze werksessie verwijderen.')

    for motivatie in werksessie_to_delete.motivaties:
        werksessie_to_delete.motivaties.remove(motivatie)
        db.session.delete(motivatie)

    db.session.delete(werksessie_to_delete)
    Verander_werksessie(None)

    if commit_to_database_success():
        return redirect(url_for('intro'))
    else:
        return render_template('error.html', melding='Kan werksessie niet verwijderen', tekst='Het verwijderen van de werksessie is mislukt. Misschien is er iets mis met de database?')
    


@app.route('/questionnaire', methods=['GET', 'POST'])
@login_required
@werksessie_required
def questionnaire():
    # Deze nieuwe implementatie van de keuzehulp is om motivaties toe te laten.
    werksessie = Werksessie.query.get_or_404(current_user.active_session)
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    
    if request.method == 'POST':
        # Als er een antwoord is gegeven door op Bevestigen te klikken
        selected_question = Vraag.query.get_or_404(request.form["vraag"])
        selected_options = request.form.getlist('optie')

        # Eerst alle opties even wissen voor deze vraag.
        for option_to_remove in selected_question.opties:
            if option_to_remove in werksessie.geselecteerde_opties:
                werksessie.geselecteerde_opties.remove(option_to_remove)
        
        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan de oude opties niet wissen', tekst='De oude opties kunnen niet worden gewist. Misschien is er een probleem met de database?')   

        # Dan alle geselecteerde opties weer aan zetten.
        for optie_id in selected_options:
            werksessie.geselecteerde_opties.append(Optie.query.get_or_404(optie_id))

        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan de niuewe opties niet toevoegen', tekst='De nieuwe opties kunnen niet worden toegevoegd. Misschien is er een probleem met de database?')   


        # Bestaande motivaties wissen
        for motivatie in werksessie.motivaties:
            if motivatie.vraag == int(request.form["vraag"]):
                werksessie.motivaties.remove(motivatie)
                if commit_to_database_success():
                    pass
                else:
                    pass # Soms lukt het niet de bestaande motivatie te wissen. Nu faalt hij stilletjes, dat is niet goed.
                    #return render_template('error.html', melding='Kan de motivatie niet opslaan', tekst=f'De motivatie kon niet worden opgeslagen. Misschien is er een probleem met de database? Hier ging het mis: {motivatie.vraag}={int(request.form["vraag"])}')

        # Nieuwe motivatie toevoegen
        motivatie = Motivaties(motivatie=request.form["motivatie"], vraag=request.form["vraag"])
        werksessie.motivaties.append(motivatie)
        db.session.add(motivatie)
        if commit_to_database_success():
            return redirect(url_for('questionnaire'))
        else:
            return render_template('error.html', melding='Kan de motivatie niet opslaan', tekst='De motivatie kon niet worden opgeslagen. Misschien is er een probleem met de database?')   

    return render_template('questionnaire.html',
                           werksessie=werksessie,
                           instrumenten=get_instruments(alle_instrumenten, werksessie),
                           categorieen=Categorie.query.order_by(Categorie.naam).all())

@app.route('/final', methods=['GET', 'POST'])
@login_required
@werksessie_required
def final():
    huidige_werksessie = Werksessie.query.get_or_404(current_user.active_session)
    alle_instrumenten=Instrument.query.order_by(Instrument.naam).all()
    form = WerksessieForm(conclusie=huidige_werksessie.conclusie)
    if request.method == 'POST':
        huidige_werksessie.conclusie = request.form['conclusie']

        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan wijzigingen niet opslaan', tekst='Het opslaan van wijzigingen aan de werksessie is mislukt. Misschien is er iets mis met de database?')      
    return render_template('final.html',
                            form=form,
                            werksessie=huidige_werksessie, 
                            actieve_werksessie=current_user.active_session,
                            instrumenten=get_instruments(alle_instrumenten, huidige_werksessie),
                            categorieen=Categorie.query.order_by(Categorie.naam).all())



@app.route('/checkout')
@login_required
@werksessie_required
def checkout():
    werksessie = Werksessie.query.get_or_404(current_user.active_session)
    alle_instrumenten=Instrument.query.order_by(Instrument.naam).all()
    return render_template('export.html',
                           werksessie=werksessie,
                           instrumenten=get_instruments(alle_instrumenten, werksessie),
                           categorieen=Categorie.query.order_by(Categorie.naam).all())


@app.route('/remove_option/<int:optie_id>')
@login_required
def remove_option_from_questionnaire(optie_id):
    werksessie = Werksessie.query.get_or_404(current_user.active_session)
    option_to_remove=Optie.query.get_or_404(optie_id)

    werksessie.geselecteerde_opties.remove(option_to_remove)

    if commit_to_database_success():
        return redirect(url_for('questionnaire'))
    else:
        return render_template('error.html', melding='Kan optie niet deselecteren', tekst='De optie kan niet worden gedeselecteerd. Misschien is er een probleem met de database?')   

@app.route('/summary')
def instrumenten_summary():
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    alle_categorieen = Categorie.query.order_by(Categorie.naam).all()
    return render_template('instrumenten_summary.html', 
                           instrumenten=alle_instrumenten, 
                           categorieen=alle_categorieen)

@app.route('/export_all_instruments')
def export_all_instruments():
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    catalogus = export_catalogus_to_word(alle_instrumenten, filename='temp.docx')
    return send_file(catalogus, as_attachment=True, download_name='catalogus.docx')

@app.route('/instrument/<int:id>')
def instrument(id):
    current_instrument = Instrument.query.get_or_404(id)
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    for i in alle_instrumenten:
        i.intro=bleach.clean(i.intro)
        i.beschrijving=bleach.clean('' if i.beschrijving is None else i.beschrijving).replace('\n', '<br>')
        i.afwegingen=bleach.clean('' if i.afwegingen is None else i.afwegingen).replace('\n', '<br>')
        i.voorbeelden=bleach.clean('' if i.voorbeelden is None else i.voorbeelden).replace('\n', '<br>')
        i.links=bleach.clean('' if i.links is None else i.links).replace('\n', '<br>')
        i.eigenaar=bleach.clean('' if i.eigenaar is None else i.eigenaar)
        i.eigenaar_email=bleach.clean('' if i.eigenaar_email is None else i.eigenaar_email)
    return render_template('/instrument.html', instrument=current_instrument, instrumenten=alle_instrumenten)

@app.route('/instrument_add', methods=['GET', 'POST'])
@admin_required
def add_instrument():
    if request.method == 'POST':
        new_instrument = Instrument(naam=request.form['naam'], 
                                       intro=request.form['intro'], 
                                       beschrijving=request.form['beschrijving'],
                                       afwegingen=request.form['afwegingen'],
                                       voorbeelden=request.form['voorbeelden'],
                                       links=request.form['links'],
                                       eigenaar=request.form['eigenaar'],
                                       eigenaar_email=request.form['eigenaar_email']
                                       )
        db.session.add(new_instrument)
        if commit_to_database_success():
            return redirect(url_for('add_tag_to_instrument', id=new_instrument.id))
        else:
            return render_template('error.html', melding='Kan instrument niet opslaan', tekst='Het opslaan van het instrument is mislukt. Misschien is er een probleem met de database?')
    
    form = InstrumentForm()
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    return render_template('add_instrument.html',
                            form=form, 
                            instrumenten=alle_instrumenten)

@app.route('/instrument_delete/<int:id>')
@admin_required
def delete_instrument(id):
    instrument_to_delete = Instrument.query.get_or_404(id)
    db.session.delete(instrument_to_delete)
    if commit_to_database_success():
        return redirect(url_for('instrumenten_summary'))
    else:
        return render_template('error.html', melding='Kan instrument niet verwijderen', tekst='Het verwijderen van het instrument is mislukt. Misschien is er iets mis met de database?')

@app.route('/instrument_update/<int:id>', methods=['GET', 'POST'])
@admin_required
def update_instrument(id):
    instrument_to_edit = Instrument.query.get_or_404(id)

    if request.method == 'POST':
        instrument_to_edit.naam=request.form['naam']
        instrument_to_edit.intro=request.form['intro']
        instrument_to_edit.beschrijving=request.form['beschrijving']
        instrument_to_edit.afwegingen=request.form['afwegingen']
        instrument_to_edit.links=request.form['links']
        instrument_to_edit.voorbeelden=request.form['voorbeelden']
        instrument_to_edit.eigenaar=request.form['eigenaar']
        instrument_to_edit.eigenaar_email=request.form['eigenaar_email']

        if commit_to_database_success():
            return redirect(url_for('instrument', id=id ))
        else:
            return render_template('error.html', melding='Kan wijzigingen niet opslaan', tekst='Het opslaan van het instrument is mislukt. Misschien is er iets mis met de database?')

    form = InstrumentForm(naam=instrument_to_edit.naam,
                            intro=instrument_to_edit.intro,
                            beschrijving=instrument_to_edit.beschrijving,
                            afwegingen=instrument_to_edit.afwegingen,
                            voorbeelden=instrument_to_edit.voorbeelden,
                            links=instrument_to_edit.links,
                            eigenaar=instrument_to_edit.eigenaar,
                            eigenaar_email=instrument_to_edit.eigenaar_email)
    return render_template('/add_instrument.html', 
                            instrument=instrument_to_edit, 
                            instrumenten=Instrument.query.order_by(Instrument.naam).all(), 
                            form=form)

@app.route('/instrument_tags/<int:id>')
@app.route('/add_instrument_tags/<int:id>/tag/<int:tag_id>')
@app.route('/add_instrument_extags/<int:id>/tag/<int:tag_id>')
@app.route('/delete_instrument_tags/<int:id>/tag/<int:tag_id>')
@admin_required
def add_tag_to_instrument(id, tag_id=-1):
    instrument_to_edit = Instrument.query.get_or_404(id)

    if "add_instrument_tag" in request.path:
        tag_to_add = Tag.query.get_or_404(tag_id)
        if tag_to_add in instrument_to_edit.extags:
            instrument_to_edit.extags.remove(tag_to_add)
        instrument_to_edit.tags.append(tag_to_add) 

        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan tag niet toevoegen', tekst='Het toevoegen van de tag aan het instrument is mislukt. Misschien is er een probleem met de database?')
    
    if "add_instrument_extag" in request.path:
        tag_to_add = Tag.query.get_or_404(tag_id)
        if tag_to_add in instrument_to_edit.tags:
            instrument_to_edit.tags.remove(tag_to_add)
        instrument_to_edit.extags.append(tag_to_add) 

        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan mintag niet toevoegen', tekst='Het toevoegen van de mintag aan het instrument is mislukt. Misschien is er een probleem met de database?')
    
    elif "delete_instrument_tag" in request.path:
        tag_to_delete = Tag.query.get_or_404(tag_id)
        if tag_to_delete in instrument_to_edit.tags:
            instrument_to_edit.tags.remove(tag_to_delete)
        if tag_to_delete in instrument_to_edit.extags:
            instrument_to_edit.extags.remove(tag_to_delete)

        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan tag niet verwijderen', tekst='Het verwijderen van de tag van het instrument is mislukt. Misschien is er een probleem met de database?')

    selected_tags = []
    for tag in Tag.query.order_by(Tag.naam).all():
        selected_tags.append([tag.id, tag.naam, tag in instrument_to_edit.tags, tag in instrument_to_edit.extags])

    return render_template('instrument_tags.html', 
                            instrument=instrument_to_edit, 
                            tags=selected_tags,
                            instrumenten=Instrument.query.order_by(Instrument.naam).all())

@app.route('/tags', methods=['GET', 'POST'])
@admin_required
def tags():
    if request.method == 'POST':
        tag_name = request.form['Tag']
        new_tag = Tag(naam=tag_name)
        db.session.add(new_tag)
        if commit_to_database_success():
            return redirect(url_for('tags'))
        else:
            return render_template('error.html', melding='Kan tag niet opslaan', tekst='Het opslaan van de tag is mislukt. Misschien is er een probleem met de database?')

    alle_tags = Tag.query.order_by(Tag.naam).all()
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    return render_template('tags.html', tags=alle_tags, instrumenten=alle_instrumenten)

@app.route('/tag_delete/<int:id>')
@admin_required
def delete_tag(id):
    tag_to_delete = Tag.query.get_or_404(id)
    db.session.delete(tag_to_delete)
    if commit_to_database_success():
        return redirect(url_for('tags'))
    else:
        return render_template('error.html', melding='Kan tag niet verwijderen', tekst='Het verwijderen van de tag is mislukt. Misschien is er een probleem met de database?')

@app.route('/tag_update/<int:id>', methods=['GET', 'POST'])
@admin_required
def update_tag(id):
    tag_to_update = Tag.query.get_or_404(id)

    if request.method == 'POST':
        tag_to_update.naam = request.form['Tag']
        if commit_to_database_success():
            return redirect(url_for('tags'))
        else:
            return render_template('error.html', melding='Kan tag niet hernoemen', tekst='Het hernoemen van de tag is mislukt. Misschien is er een probleem met de database?')

    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    return render_template('/update_tag.html', tag=tag_to_update, instrumenten=alle_instrumenten)

@app.route('/question_tools', methods=['GET', 'POST'])
@admin_required
def question_tools():
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    alle_categorieen = Categorie.query.order_by(Categorie.naam).all()
    alle_vragen = Vraag.query.order_by(Vraag.categorie_id).all()

    if request.method == 'POST':
        if request.form['submit_button'] == 'Categorie toevoegen':
            categorie_name = request.form['Categorie']
            new_categorie = Categorie(naam=categorie_name)
            db.session.add(new_categorie)
            if commit_to_database_success():
                return redirect(url_for('question_tools'))
            else:
                return render_template('error.html', melding='Kan categorie niet opslaan', tekst='Het opslaan van de categorie is mislukt. Misschien is er een probleem met de database?')
        if request.form['submit_button'] == 'Vraag toevoegen':
            vraag_categorie = Categorie.query.filter_by(naam=request.form['Categorienaam']).first()
            new_vraag = Vraag(naam=request.form['Vraag'], multiselect=False)             
            vraag_categorie.vragen.append(new_vraag)
            db.session.add(vraag_categorie)
            db.session.add(new_vraag)
            if commit_to_database_success():
                return redirect(url_for('question_tools'))
            else:
                return render_template('error.html', melding='Kan vraag niet opslaan', tekst='Het opslaan van de vraag is mislukt. Misschien is er een probleem met de database?')

    return render_template('question_tools.html', 
                        categorieen=alle_categorieen, 
                        vragen=alle_vragen,
                        instrumenten=alle_instrumenten)


@app.route('/categorie_delete/<int:id>')
@admin_required
def delete_categorie(id):
    categorie_to_delete = Categorie.query.get_or_404(id)
    db.session.delete(categorie_to_delete)
    if commit_to_database_success():
        return redirect(url_for('question_tools'))
    else:
        return render_template('error.html', melding='Kan categorie niet verwijderen', tekst='Het verwijderen van de categorie is mislukt. Misschien bevat de categorie nog vragen? Als een categorie nog vragen bevat dan kan de categorie niet worden verwijderd. Verwijder eerst alle vragen en probeer het opnieuw.')

@app.route('/categorie_update/<int:id>', methods=['GET', 'POST'])
@admin_required
def update_categorie(id):
    categorie_to_update = Categorie.query.get_or_404(id)
    if request.method == 'POST':
        categorie_to_update.naam = request.form['Categorie']
        if commit_to_database_success():
            return redirect(url_for('question_tools'))
        else:
            return render_template('error.html', melding='Kan categorie niet hernoemen', tekst='Het hernoemen van de categorie is mislukt. Misschien is er een probleem met de database?')

    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    return render_template('/update_category.html', categorie=categorie_to_update, instrumenten=alle_instrumenten)

@app.route('/question/<int:vraag_id>/update', methods=['GET', 'POST'])
@admin_required
def question_update(vraag_id):
    vraag_to_update = Vraag.query.get_or_404(vraag_id)
    if request.method == 'POST':
        nieuwe_categorie = Categorie.query.filter_by(naam=request.form['Categorienaam']).first()
        vraag_to_update.naam = request.form['Vraag']
        vraag_to_update.categorie_id = nieuwe_categorie.id
        if commit_to_database_success():
            return redirect(url_for('question', vraag_id=vraag_to_update.id))
        else:
            return render_template('error.html', melding='Kan vraag niet wijzigen', tekst='Het wijzigen van de vraag is mislukt. Misschien is er een probleem met de database?')

    return render_template('/update_question.html', 
                        categorieen=Categorie.query.order_by(Categorie.naam).all(), 
                        vraag=vraag_to_update)

@app.route('/question/<int:vraag_id>/enable_multiselect/<int:enabled>')
@admin_required
def toggle_multiselect(vraag_id, enabled=0):
    vraag_to_update = Vraag.query.get_or_404(vraag_id)
    if enabled==1:
        vraag_to_update.multiselect = True
    else:
        vraag_to_update.multiselect = False
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()
    alle_categorieen = Categorie.query.order_by(Categorie.naam).all()
    alle_vragen = Vraag.query.order_by(Vraag.categorie_id).all()

    if commit_to_database_success():
        return render_template('question_tools.html', 
                        categorieen=alle_categorieen, 
                        vragen=alle_vragen,
                        instrumenten=alle_instrumenten)
    else:
        return render_template('error.html', melding='Kan vraag niet wijzigen', tekst='Het wijzigen van de vraag is mislukt. Misschien is er een probleem met de database?')
            

@app.route('/question/<int:id>/delete')
@admin_required
def delete_vraag(id):
    vraag_to_delete = Vraag.query.get_or_404(id)
    db.session.delete(vraag_to_delete)
    if commit_to_database_success():
        return redirect(url_for('question_tools'))
    else:
        return render_template('error.html', melding='Kan vraag niet verwijderen', tekst='Het verwijderen van de vraag is mislukt. Misschien bevat de vraag nog antwoordopties? Als een vraag nog opties bevat dan kan de vraag niet worden verwijderd. Verwijder eerst alle antwoordopties en probeer het opnieuw.')

@app.route('/question/<int:vraag_id>', methods=['GET', 'POST'])
@app.route('/question/<int:vraag_id>/add_option', methods=['GET', 'POST'])
@admin_required
def question(vraag_id):
    huidige_vraag = Vraag.query.get_or_404(vraag_id)
    if request.method == 'POST':       
        optie_to_add = Optie(naam=request.form['Optie'])
        huidige_vraag.opties.append(optie_to_add)
        if commit_to_database_success():
            return redirect(url_for('question', vraag_id=huidige_vraag.id))
        else:
            return render_template('error.html', melding='Kan optie niet toevoegen', tekst='Het toevoegen van de optie is mislukt. Misschien is er een probleem met de database?')
    
    return render_template('question.html',
                            vraag=huidige_vraag,
                            categorie=Categorie.query.get_or_404(huidige_vraag.categorie_id),
                            instrumenten=Instrument.query.order_by(Instrument.naam).all())

@app.route('/question/<int:vraag_id>/update_option/<int:option_id>', methods=['GET', 'POST'])
@admin_required
def update_option(vraag_id, option_id=0):
    huidige_vraag = Vraag.query.get_or_404(vraag_id)
    alle_instrumenten = Instrument.query.order_by(Instrument.naam).all()

    if request.method == 'POST':       
        optie_to_update = Optie.query.get_or_404(option_id)
        optie_to_update.naam = request.form['Optie']
        if commit_to_database_success():
            return redirect(url_for('question', vraag_id=huidige_vraag.id))
        else:
            db.session.rollback()
            return render_template('error.html', melding='Kan optie niet hernoemen', tekst='Het hernoemen van de optie is mislukt. Misschien is er een probleem met de database?')

    return render_template('update_option.html',
                        optie=Optie.query.get_or_404(option_id),
                        vraag=huidige_vraag,
                        instrumenten=alle_instrumenten)

@app.route('/question/<int:vraag_id>/delete_option/<int:option_id>', methods=['GET', 'POST'])
@admin_required
def delete_option(vraag_id, option_id):
    optie_to_delete = Optie.query.get_or_404(option_id)
    optie_to_delete.tags=[]
    optie_to_delete.tags_exclusief=[]
    db.session.delete(optie_to_delete)
    if commit_to_database_success():
        return redirect(url_for('question', vraag_id=vraag_id, option_id=option_id))
    else:
        return render_template('error.html', melding='Kan optie niet verwijderen', tekst='Het verwijderen van de optie is mislukt. Misschien is er een probleem met de database?')

@app.route('/question/<int:vraag_id>/option/<int:option_id>/tags')
@app.route('/question/<int:vraag_id>/option/<int:option_id>/add_tag/<int:tag_id>', methods=['GET', 'POST'])
@app.route('/question/<int:vraag_id>/option/<int:option_id>/delete_tag/<int:tag_id>', methods=['GET', 'POST'])
@admin_required
def add_tag_to_option(vraag_id, option_id, tag_id=-1):
    huidige_vraag = Vraag.query.get_or_404(vraag_id)
    option_to_edit = Optie.query.get_or_404(option_id)
    if "add_tag" in request.path:
        tag_to_add = Tag.query.get_or_404(tag_id)
        option_to_edit.tags.append(tag_to_add) 
        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan tag niet toevoegen', tekst='Het toevoegen van de tag is mislukt. Misschien is er een probleem met de database?')
    elif "delete_tag" in request.path:
        tag_to_delete = Tag.query.get_or_404(tag_id)
        option_to_edit.tags.remove(tag_to_delete) 
        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan tag niet verwijderen', tekst='Het verwijderen van de tag is mislukt. Misschien is er een probleem met de database?')

    selected_tags = []
    for tag in Tag.query.order_by(Tag.naam).all():
        selected_tags.append([tag.id, tag.naam, tag in option_to_edit.tags])
    if request.method == 'POST':     
        if commit_to_database_success():
            pass
        else:
            return render_template('error.html', melding='Kan tag niet toevoegen', tekst='Het toevoegen van de tag is mislukt. Misschien is er een probleem met de database?')
    
    return render_template('option_tags.html', 
                            vraag=huidige_vraag,
                            optie=option_to_edit, 
                            tags=selected_tags,
                            instrumenten=Instrument.query.order_by(Instrument.naam).all())



@app.route('/export_session')
@login_required
@werksessie_required
def export_session_word():
    werksessie = Werksessie.query.get_or_404(current_user.active_session)
    alle_instrumenten=Instrument.query.order_by(Instrument.naam).all()
    categorieen=Categorie.query.order_by(Categorie.naam).all()
    sessie = export_session_to_word(werksessie=werksessie, 
                                    vraagcategorieen=categorieen, 
                                    instrumenten=get_instruments(alle_instrumenten, werksessie), 
                                    filename='temp.docx')
    return send_file(sessie, as_attachment=True, download_name=f'Verslag {werksessie.naam}.docx')

@app.route('/export_instrument/<int:instrument_id>')
@login_required
def export_instrument_word(instrument_id):
    instrument_to_export = Instrument.query.get_or_404(instrument_id)
    instrument_word = export_catalogus_to_word([instrument_to_export], filename='temp.docx')
    return send_file(instrument_word, as_attachment=True, download_name=f'{instrument_to_export.naam}.docx')

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)