const ws = require("ws")
const fs = require("fs")

const f = fs.createWriteStream("dataset.csv")
let written = 0

function start(){
    const sock = new ws.WebSocket("wss://ws-feed.exchange.coinbase.com");
    const pairs = [ "ETH-EUR", "DOGE-EUR", "BCH-EUR", "BTC-EUR", "LTC-EUR" ];
    sock.on("open", (evt) => {
        console.log("Open: ", evt)
        sock.send(JSON.stringify(
            {
                "type": "subscribe",
                "product_ids": pairs,
                "channels": [
                    {
                        "name": "ticker",
                        "product_ids": pairs
                    }
                ]
            }
        ))
    })

    sock.on("message", (evt) => {
        const obj = JSON.parse(evt.toString("utf-8"));
        if(typeof(obj.type) == "undefined" || obj.type !== "ticker") return;
        const row = [
            obj.sequence,
            obj.product_id,
            obj.price,
            obj.best_bid,
            obj.best_ask,
            obj.side,
            obj.time,
            obj.trade_id
        ].join(",") + "\n"
        f.write(row)
        written += row.length
        //console.log("Message: ", JSON.parse(evt.toString("utf-8")))
    })

    sock.on("close", (evt) => {
        console.log("Close: ", evt)
        setTimeout(start, 1000);
    })
}

start()

let last = 0
setInterval(() => {
    console.log(new Date(), written, written - last)
    last = written
}, 30000)