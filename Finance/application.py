import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    # get user cash total
    result = db.execute("SELECT cash FROM users WHERE id=:id", id=session["user_id"])
    cash = result[0]['cash']

    # pull all transactions belonging to user
    portfolio = db.execute("SELECT symbol, share, price FROM transactions WHERE user_id=:id", id=session["user_id"])

    if not portfolio:
        return apology("sorry you have no holdings")

    stock_summary = db.execute("SELECT symbol, sum(share) as sum_share, sum(share * price) as share_total FROM transactions WHERE user_id=:id group by symbol", id=session["user_id"])

    # determine current price, stock total value and grand total value

    for ss_dict in stock_summary:
        ss_dict["current_price"] = lookup(ss_dict["symbol"])["price"]
        ss_dict["share_total"] = round(ss_dict["share_total"], 2)
    

    return render_template("index.html", stock_summary=stock_summary)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    if request.method == "POST":

        number_shares = int(request.form.get("shares"))
        
        user_id = session["user_id"]

        # ensure name of stock was submitted
        if (not request.form.get("symbol")) or (not request.form.get("shares")):
            return apology("must provide stock symbol and shares")

        if number_shares <= 0:
            return apology("must put valid number of shares")

        # Lookup using API key and gets current price for stock
        quote = lookup(request.form.get("symbol"))

        if quote == None:
            return apology("Stock symbol not valid")

        symbol = quote['symbol']
        price = quote['price']

        # Getting cash amount from the users
        result_cash = db.execute("SELECT cash FROM users WHERE id=:id", id=user_id)
        cash = result_cash[0]['cash']

        stock_transaction = db.execute("SELECT sum(share * price) as share_total FROM transactions WHERE user_id=:id", id=user_id)

        # Trans Amount is the total transaction amount from the database
        trans_amount = stock_transaction[0]['share_total']
        
        # current balance is intial cash minus trans amount
        current_balance = cash - trans_amount
        
        # Cost is the price * shares that users requested now to buy
        cost = number_shares * price
        
        # Checking if user can buy the shares requested
        if current_balance < cost:
            return apology("Sorry, you don't have enough cash to buy this stock")

        trans_date = datetime.now()

        transaction = {
            'symbol' : symbol,
            'price' : price,
            'shares' : number_shares,
            'company' : quote['name'],
            'user_id' : user_id,
            'cost' : cost,
            'date' : trans_date
        }

        add_transaction = db.execute("INSERT INTO transactions (user_id, symbol, share, price) VALUES (:user_id, :symbol, :number_shares, :price)", user_id=user_id, symbol=symbol, number_shares=number_shares, price=price)

        return render_template("bought.html", transaction = transaction)

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    # getting user's cash
    result = db.execute("SELECT cash FROM users WHERE id=:id", id=session["user_id"])
    cash = result[0]['cash']

    # pull all transactions belonging to user
    portfolio = db.execute("SELECT symbol, share, price, trans_date FROM transactions WHERE user_id=:id", id=session["user_id"])

    if not portfolio:
        return apology("sorry you have no holdings")

    grand_total = 0

    # to find the current price, stock total value and the total value
    for transactions in portfolio:
        price = transactions['price']
        share = transactions['share']
        trans_type = "Buy" if share > 0 else "Sell" 
        total = share * price
        transactions.update({'total': abs(total), 'share': abs(share), 'trans_type': trans_type})
        cash -= total
        grand_total += total
        

    return render_template("history.html", transactions=portfolio, cash=cash, total=grand_total, price=price)



@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect(url_for("index"))

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user."""

    # if user reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 404)

        # ensure password and password confirmation were submitted
        elif not request.form.get("password") or not request.form.get("password_confirm"):
            return apology("must provide password", 403)

        # ensure password and password confirmation match
        elif request.form.get("password") != request.form.get("password_confirm"):
            return apology("password and password confirmation must match", 403)

        username=request.form.get("username")
        password=request.form.get("password")

        # hash password
        hash = generate_password_hash(password)
        
        try:
            # add user to database
            result = db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)", username=username, hash=hash)
            return redirect("/")

        except Exception as e:
            return apology("This username is already taken, please try with a different username")

        

    else:
        return render_template("register.html")

@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":

        # checking if name of stock was submitted
        if not request.form.get("symbol"):
            return apology("must provide stock symbol")

        quote = lookup(request.form.get("symbol"))

        if quote == None:
            return apology("Stock symbol not valid")


        else:
           return render_template("quoted.html", quote=quote)

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("quote.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock."""

    # if user reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        quote = lookup(request.form.get("symbol"))

        if quote == None:
            return apology("Stock symbol not valid")

        symbol = quote['symbol']
        price = quote['price']

        user_id = session["user_id"]

        number_shares = int(request.form.get("shares"))

        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


        #symbol=request.form.get("symbol")

        # ensure stock symbol and number of shares was submitted
        if (not request.form.get("symbol")) or (not request.form.get("shares")):
            return apology("must provide stock symbol and shares")

        # ensure number of shares is valid
        if number_shares <= 0:
            return apology("must provide valid number of shares (integer)")

        available = db.execute("SELECT sum(share) as sum_share FROM transactions WHERE symbol=:symbol and user_id=:id", symbol=symbol, id=session["user_id"])

        # check that number of shares being sold does not exceed quantity in portfolio
        if number_shares > available[0]["sum_share"]:
            return apology("You may not sell more shares than you currently hold")

        # check is valid stock name provided
        if quote == None:
            return apology("Stock symbol not valid, please try again")

        number_shares = -int(request.form.get("shares"))

        # calculate cost of transaction
        cost = number_shares * price

        # update cash amount in users database
        #db.execute("UPDATE users SET cash=cash+:cost WHERE id=:id", cost=cost, id=session["user_id"]);

        transaction = {
            'symbol' : symbol,
            'price' : price,
            'shares' : number_shares,
            'company' : quote['name'],
            'user_id' : user_id,
            'cost' : cost,
            'date' : date
        }

        add_transaction = db.execute("INSERT INTO transactions (user_id, symbol, share, price) VALUES (:user_id, :symbol, :number_shares, :price)", user_id=user_id, symbol=symbol, number_shares=number_shares, price=price)

        return redirect(url_for("index"))

    else:
        return render_template("sell.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
