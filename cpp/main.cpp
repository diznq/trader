#include <fstream>
#include <sstream>
#include <iostream>
#include <thread>
#include <mutex>
#include <vector>
#include <deque>
#include <random>
#include "argparse.hpp"
#include "date.h"

// this is why they call C++ cancer
typedef std::chrono::time_point<std::chrono::system_clock, std::chrono::microseconds> timestamp;

int ROLL_MIN = 10;
int ROLL_MAX = 560;
int ROLL_SCALE = 1;
int SELL_TIMEOUT = 0;
int BUY_TIMEOUT = 0;

double DIP_MAX=0.2;
double SELL_MAX=0.2;
double BUY_UNDERPRICE=0.01;

#define MAKER_FEE 0.005
#define TAKER_FEE 0.005
#define MINUTE 60000000LL

enum class State {
    BUY,
    BUYING,
    SELLING
};

struct Record {
    long long time;
    double price;
    double max;
    double change;

    Record(const std::string& line) {
        //14229070888,BTC-EUR,40999.76,40999.76,41006.87,sell,2022-01-05T08:20:36.479940Z,57916989
        std::stringstream ss(line);
        std::string part;
        int i=0;
        while(std::getline(ss, part, ',')){
            if(i == 2) {    // price
                price = atof(part.c_str());
            } else if(i == 6){  // time
                std::istringstream ss(part);
                timestamp t;
                ss >> date::parse("%FT%TZ", t);
                time = t.time_since_epoch().count();
            }
            i++;
        }
    }
};

std::vector<Record> roll(const std::vector<Record>& records, long long minutes){
    long long window = minutes * 60000000;
    std::vector<Record> copy(records);
    std::deque<Record> frame;

    double maxSoFar = 0.0;
    long long maxTime = 0;

    // This implementation is inefficient as hell, but simple enough
    for(size_t i=0; i<copy.size(); i++){
        Record& now = copy[i];
        frame.emplace_back(now);
        if(now.price > maxSoFar){
            maxSoFar = now.price;
            maxTime = now.time;
        }

        long long bound = now.time - window;
        while(!frame.empty() && frame.front().time < bound){
            frame.pop_front();
        }

        if(maxTime < bound){
            maxSoFar = 0.0;
        }

        if(maxSoFar == 0.0){
            for(Record& rec : frame){
                if(rec.price > maxSoFar){
                    maxSoFar = rec.price;
                    maxTime = rec.time;
                }
            }
        }

        now.max = maxSoFar;
        now.change = 0.0;
        if(i > 0){
            now.change = now.price / copy[i - 1].max - 1.0;
        }
    }
    return copy;
}

class Chad {
public:
    double _buy = -0.01;
    double _sell = 0.01;
    double _ccy = 0.0;
    double _crypto = 0.0;
    double _buyPrice = -1.0;
    double _sellPrice = -1.0;
    double _buyFees = 0.0;
    long long _buyTime = 0;
    long long _buyInit = 0;
    long long _sellDuration = 0LL;
    long long _buyDuration = 0LL;
    int _buys = 0;
    int _sells = 0;
    int _timeouts = 0;
    State _state = State::BUY;

    Chad() {

    }

    Chad(double cash, double buy, double sell){
        _ccy = cash;
        _buy = buy;
        _sell = sell;
    }

    bool will_buy(double change, double price) const {
        if(_state != State::BUY) return false;
        return _ccy > 0 && change <= _buy;
    }
    
    void buy(double price){
        double amt = (_ccy / price / (1 + MAKER_FEE));
        amt = floor(amt * 1000000.0) / 1000000.0;
        if(amt <= 0.0) return;
        double cost = amt * price * (1 + MAKER_FEE);
        _ccy -= cost;
        _buyFees = cost - amt * price;
        _crypto += amt;
        _buyPrice = price;
        _buys++;
    }
        
    void sell(double price){
        _ccy += _crypto * price * (1 - TAKER_FEE);
        _crypto = 0;
        _buyPrice = -1.0;
        _sells++;
    }

    double equity(double price) const {
        return _ccy; // + _crypto * price / (1.0 + MAKER_FEE);
    }

    double step(const Record& record, double underprice, long long buy_timeout, long long sell_timeout) {
        if(will_buy(record.change, record.price)){
            _buyPrice = record.price * (1 - underprice);
            _buyInit = record.time;
            _state = State::BUYING;
        }

        if(_state == State::BUYING){
            if(record.price <= _buyPrice){
                buy(_buyPrice);
                _buyTime = record.time;
                _sellPrice = _buyPrice * (1.0 + _sell);
                _sellPrice = (_sellPrice * _crypto + _buyFees) / _crypto;
                _sellPrice = _sellPrice / (1 - MAKER_FEE);
                _buyDuration += _buyTime - _buyInit;
                _state = State::SELLING;
            } else if(buy_timeout > 0L && (record.time - _buyInit) >= buy_timeout){
                _state = State::BUY;
                _timeouts++;
            }
        } else if(_state == State::SELLING){
            if(record.price >= _sellPrice){
                sell(_sellPrice);
                _sellDuration += (record.time - _buyTime);
                _state = State::BUY;
            } else if(sell_timeout > 0L && (record.time - _buyTime) >= sell_timeout){
                sell(_buyPrice);
                _sellDuration += (record.time - _buyTime);
                _state = State::BUY;
            }
        }
        return equity(record.price);
    }

};

std::vector<std::vector<Record>> rolls;

double best = -1.0;
std::mutex mtx;

void worker(){
    std::random_device dev;
    std::mt19937 rng(dev());
    std::uniform_int_distribution<std::mt19937::result_type> wnd(ROLL_MIN, ROLL_MAX);
    std::uniform_int_distribution<std::mt19937::result_type> bto(0, BUY_TIMEOUT);
    std::uniform_int_distribution<std::mt19937::result_type> sto(0, SELL_TIMEOUT);
    std::uniform_real_distribution<double> dbl;

    while(true){
        int window = wnd(rng) * ROLL_SCALE;
        double buy = dbl(rng) * -DIP_MAX;
        double sell = dbl(rng) * SELL_MAX;
        double underprice = dbl(rng) * BUY_UNDERPRICE;
        int bt = bto(rng);
        int st = sto(rng);
        Chad ch(1000.0, buy, sell);
        std::vector<Record>& arr = rolls[window];
        for(Record& rec : arr){
            ch.step(rec, underprice, bt * MINUTE, st * MINUTE);
        }
        if(ch._crypto > 0)
            ch.sell(arr.back().price);
        double eq = ch.equity(arr.back().price);
        mtx.lock();
        if(eq > best && ch._sells > 0){
            best = eq;
            printf("Chad(buy=%.6f, sell=%.6f, under=%.4f, window=%3d, bto: %3d, sto: %3d): %.3f | buys=%d, sells=%d, btos: %d, bavg: %lld min, savg: %lld min\n", 
                    buy, sell, underprice, window, bt, st, eq, ch._buys, ch._sells, ch._timeouts, ch._buyDuration / ch._buys / MINUTE, ch._sellDuration / ch._sells / MINUTE);
        }
        mtx.unlock();
    }
}

int main(int argc, const char **argv){
    argparse::ArgumentParser parser("simulation");
    
    parser
        .add_argument("--pair")
        .default_value<std::string>("LTC-EUR")
        .help("traded pair, i.e. BTC-EUR");

    parser
        .add_argument("--csv")
        .default_value<std::string>("../stock_dataset.csv")
        .help("input dataset");

    parser
        .add_argument("--buy")
        .default_value<double>(0.05)
        .help("buy threshold")
        .scan<'f', double>();

    parser
        .add_argument("--sell")
        .default_value<double>(0.05)
        .help("sell threshold")
        .scan<'f', double>();
        
    parser
        .add_argument("--under")
        .default_value<double>(0.01)
        .help("buy underprice")
        .scan<'f', double>();

    parser
        .add_argument("--rmin")
        .default_value<int>(10)
        .help("rollinig window minimum size")
        .scan<'i', int>();

    parser
        .add_argument("--rmax")
        .default_value<int>(560)
        .help("rollinig window maximum size")
        .scan<'i', int>();

    parser
        .add_argument("--rscale")
        .default_value<int>(1)
        .help("rollinig window scale size")
        .scan<'i', int>();

    parser
        .add_argument("--bto")
        .default_value<int>(0)
        .help("buy timeout")
        .scan<'i', int>();

    parser
        .add_argument("--sto")
        .default_value<int>(0)
        .help("sell timeout")
        .scan<'i', int>();

    try {
        parser.parse_args(argc, argv);
    } catch(const std::runtime_error& err) {
        std::cerr << err.what() << std::endl;
        std::cerr << parser;
        return 1;
    }

    
    std::string target = parser.get<std::string>("pair");
    std::string line;
    DIP_MAX = parser.get<double>("buy");
    SELL_MAX = parser.get<double>("sell");
    BUY_UNDERPRICE = parser.get<double>("under");

    ROLL_MAX = parser.get<int>("rmax");
    ROLL_MIN = parser.get<int>("rmin");
    ROLL_SCALE = parser.get<int>("rscale");
    SELL_TIMEOUT = parser.get<int>("sto");
    BUY_TIMEOUT = parser.get<int>("bto");

    rolls.resize((ROLL_MAX + 1) * ROLL_SCALE);

    std::cout << "Loading data for " << target << " in " << parser.get<std::string>("csv") <<  std::endl;

    std::vector<Record> records;
    std::ifstream f(parser.get<std::string>("csv"));
    if(!f.is_open()){
        std::cerr << "Couldn't open input dataset!" << std::endl;
        return 1;
    }

    while(std::getline(f, line)){
        if(line.find(target) == std::string::npos) continue;
        records.emplace_back(Record(line));
    }

    std::cout << "Precomputing rolling maxes" << std::endl;

    for(int i=ROLL_MIN; i<=ROLL_MAX; i++){
        //std::cout << "Precomputing rolling max with window " << (i * ROLL_SCALE) << std::endl;
        rolls[i * ROLL_SCALE] = roll(records, i * ROLL_SCALE);
    }

    std::cout << "Simulating" << std::endl;
    std::vector<std::thread> threads;
    for(unsigned int i=0; i<std::thread::hardware_concurrency(); i++){
        threads.emplace_back(std::thread(worker));
    }
    for(std::thread& thr : threads){
        thr.join();
    }
}