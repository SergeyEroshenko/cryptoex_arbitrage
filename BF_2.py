import requests
import math
import networkx as nx
import bellmanford as bf
import time
import csv

FILENAME = "Graph.csv"

class Client(object):
    def __init__(self, url):
        self.url = url + "/api/2"
        self.session = requests.session()

    def get_symbols(self):
        """Get all symbols."""
        return self.session.get("%s/public/symbol/" % (self.url)).json()

    def get_orderbook(self, symbol_code):
        """Get orderbook. """
        return self.session.get("%s/public/orderbook/%s" % (self.url,
                                                            symbol_code)).json()

    def get_trades(self, symbol_code):
        """Get trades. """
        return self.session.get("%s/public/trades/%s" % (self.url, symbol_code)).json()
        
client = Client("https://api.hitbtc.com")

symbols = {}
symbols_lst = client.get_symbols()
cnt = 0 ##
for sym in symbols_lst:
    symbols[sym['id']] = sym
    cnt +=1 ##
    if cnt > 50 : break ##

basecurr = {}
'''
Add to the dictionary the value of the currency in the account.
The sequence of currencies is MANDATORY
'''
basecurr['USD'] = 1000
basecurr['BTC'] = 0.18
basecurr['ETH'] = 4

'''Filtering pairs by applicability to work'''
n = 7
kf = 1.003
p = 1
spread = 2
FL = (kf - 1) / p

'''Filtering by price density in the orderbook'''
def dens_price(orderbook, ask_bid, n = 7):

    s = 0
    for x in range(0, n-1):
        if ask_bid == 'ask':
            s += (float(orderbook['ask'][x+1]['price']) /
                  float(orderbook['ask'][x]['price']) - 1.0)
        else:
            s += (1.0 - float(orderbook['bid'][x+1]['price']) /
                  float(orderbook['bid'][x]['price']))
    return (n - 1.0) / s

for sym in list(symbols):

    dp_lst = []
    orderbook = client.get_orderbook(sym)
    if len(orderbook['ask']) < n :
        symbols.pop(sym)
        continue  
    if len(orderbook['bid']) < n :
        symbols.pop(sym)
        continue

    dp_lst.append(dens_price(orderbook, 'ask'))
    dp_lst.append(dens_price(orderbook, 'bid'))

    dp_min = min(dp_lst)

    if dp_min == 0 or (1.0 / dp_min) >= FL:
       symbols.pop(sym)
    
print(f'\n\nPrice density filter: {len(symbols)} pairs\n')
print(list(symbols))

'''Spread filter'''
for sym in list(symbols):

    trades = client.get_trades(sym)
    spr = spr_cnt = 0
    N_trades = len(trades)
    if N_trades > 50: N_trades = 50
	
    for i in range(0, N_trades-1):
        if ((trades[i]['side']=='sell' and trades[i+1]['side']=='buy')
         or (trades[i]['side']=='buy' and trades[i+1]['side']=='sell')):
            spr+= abs( float(trades[i+1]['price']) /
                       float(trades[i]['price']) - 1 )
            spr_cnt+=1

    if spr_cnt == 0:
        spr_pair = 0
    else:
        spr_pair = spr / spr_cnt

    if spr_pair == 0 or (spr_pair > FL / spread):
        
        symbols.pop(sym)

print(f'\n\nSpread filter: {len(symbols)} pairs\n')
print(list(symbols))

'''Construction of an unweighted graph to exclude pairs not included in triangles'''
gr = []
for sym in list(symbols):
    gr.append((symbols[sym]['baseCurrency'] ,
               symbols[sym]['quoteCurrency']))

T = nx.Graph()
T.add_edges_from(gr)
tr = nx.triangles(T)

del_point = []
for key , val in tr.items():
    if val == 0: del_point.append(key)   
        
for sym in list(symbols):
    if (symbols[sym]['baseCurrency'] in del_point
        or symbols[sym]['quoteCurrency'] in del_point):
        symbols.pop(sym)
      
print(f'\n\nPairs for subscribe: {len(symbols)} pairs\n')
print(list(symbols))
#######################################################################

'''
The function of determining transaction parameters based 
on the response of the Bellman-Ford algorithm
'''

def set_transact(path, edges, volumes, basecurr, symbols):

    work_pairs = list(symbols)
    '''Base currency search module in the chain, in accordance 
    with the priority of use'''
    sort_id = 0
    for curr in list(basecurr):
        if path.count(curr) == 0:
            sort_id = -1
            continue
        else :
            sort_id = path.index(curr)
            break

    if sort_id == -1 : return('Error: No base currency in path') 
    
    '''Sort chain to move base currency to beginning'''
    if sort_id > 0 :
        remove = path[1:sort_id+1]
        for i in range(sort_id):
            path.pop(0)
        path += remove
        
    print('Path after sort ',path)
    
    '''Make a list
    | Edge name | Edge weight | Available volume |'''
    weighted_e = []
    for i in range(0, len(path)-1):
        for idx, e in enumerate(edges):
            if path[i] == e[0] and path[i+1] == e[1]:
                if (path[i] + path[i+1]) in work_pairs :
                    pair = (path[i] + path[i+1])
                if (path[i+1] + path[i]) in work_pairs :
                    pair = (path[i+1] + path[i])

                price = math.exp(-e[2])
                size = volumes[idx][2]

                weighted_e.append((pair, price, size))
                
    '''Compiling a list of available volumes in terms of the 
    base currency of the chain'''
    v_sort_list = []
    v_sort_list.append(1)
    for i in range(1, len(weighted_e)+1):
        v_sort_list.append(weighted_e[i-1][1] * v_sort_list[i-1])

    v_sort_list[-1] = 1    
    
    for i in range(0, len(path)-1):
        pair = path[i] + path[i+1]
        pair_reverse = path[i+1] + path[i]

        if (pair) in work_pairs:
            v_sort_list[i] = float(weighted_e[i][2]) / float(v_sort_list[i])
                
        if (pair_reverse) in work_pairs:
            v_sort_list[i] = float(weighted_e[i][2]) / float(v_sort_list[i+1])


    baseCurrBalance = basecurr[path[0]]

    v_sort_list[-1] = baseCurrBalance                
    
    '''Making a list of volumes'''
    qi = float(symbols[weighted_e[0][0]]['quantityIncrement'])
    startVol = min(v_sort_list)
    startVol = (int(startVol/qi)) * qi
    vol_list = []
    
    vol_list.append(startVol)
    for idx, we in enumerate(weighted_e):
        qi = float(symbols[we[0]]['quantityIncrement'])
        vol_list.append(int((vol_list[idx] * we[1])/qi) * qi)

    if 0 in vol_list : return("Error: Not enought size in Orderbook's. Size disbalance.")

    '''Making a list of transaction parameters'''
    transact_list = []
    for i in range(0, len(path)-1):
        pair = path[i] + path[i+1]
        pair_reverse = path[i+1] + path[i]

        if (pair) in work_pairs:
            symbol = pair
            side = 'sell'
            vol = vol_list[i]

                
        if (pair_reverse) in work_pairs:
            symbol = pair_reverse
            side = 'buy'
            vol = vol_list[i+1]

        act = (symbol, side, vol)
        transact_list.append(act)
        
    return transact_list

'''Analyze the graph in an infinite loop'''
cnt = 0
while True:
    cnt += 1
'''Getting the current exchange prices for assigning 
the weights of the edges'''
    edges =[]
    volumes=[]
    for sym in symbols:
        
        orderbook = client.get_orderbook(sym)
        fee = float(symbols[sym]['takeLiquidityRate'])
        baseCurr  = (symbols[sym]['baseCurrency'])
        quoteCurr = (symbols[sym]['quoteCurrency'])
        
        price_to   = (-math.log(float(orderbook['bid'][0]['price'])
                                * (1 - fee)))
        price_from = (-math.log(1 / float(orderbook['ask'][0]['price'])
                                / (1 + fee)))
        
        edges.append((baseCurr , quoteCurr, price_to))
        edges.append((quoteCurr, baseCurr , price_from))

        vol_to   = orderbook['bid'][0]['size']
        vol_from = orderbook['ask'][0]['size']
        
        volumes.append((baseCurr , quoteCurr, vol_to))
        volumes.append((quoteCurr, baseCurr , vol_from))
        
    G = nx.DiGraph()
    G.add_weighted_edges_from(edges)

    '''Search for negative cycles in a graph using the 
    Bellman-Ford algorithm'''
    bf_result = bf.negative_edge_cycle(G)
    print('\nBellman-Ford answer #', cnt,': ', bf_result)

    profit = bf_result[0]
    path = bf_result[1]

    '''If a negative cycle is found, calculate the parameters 
    for the transaction and send them to the transaction module. 
    Subject to exceeding the minimum profitability.'''
    if bf_result[2] == True :
        profit = -profit
        print('\nProfit = ', (profit * 100),' %')
        print('\nPath before sort ', path)
        transact = set_transact(path, edges, volumes, basecurr, symbols)
        print('\n',transact)
        if type(transact) is str : break
        if profit > (kf - 1):
            print('\nGood chain! Go to trade 8-)')
    else :
        print('\nNo Profit')    

