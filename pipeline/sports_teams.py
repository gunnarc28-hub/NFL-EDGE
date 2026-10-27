"""NBA and NHL teams: names and chip colors (c1 background, c2 text). Abbreviations follow ESPN for the NBA
and the NHL's own site for the NHL (ESPN's NHL abbreviations map through ESPN_NHL)."""
NBA = {
    'ATL': ('Atlanta', 'Hawks', '#E03A3E', '#FFFFFF'), 'BOS': ('Boston', 'Celtics', '#007A33', '#FFFFFF'), 'BKN': ('Brooklyn', 'Nets', '#000000', '#FFFFFF'),
    'CHA': ('Charlotte', 'Hornets', '#1D1160', '#00A3AD'), 'CHI': ('Chicago', 'Bulls', '#CE1141', '#FFFFFF'), 'CLE': ('Cleveland', 'Cavaliers', '#860038', '#FDBB30'),
    'DAL': ('Dallas', 'Mavericks', '#00538C', '#FFFFFF'), 'DEN': ('Denver', 'Nuggets', '#0E2240', '#FEC524'), 'DET': ('Detroit', 'Pistons', '#C8102E', '#FFFFFF'),
    'GS': ('Golden State', 'Warriors', '#1D428A', '#FFC72C'), 'HOU': ('Houston', 'Rockets', '#CE1141', '#FFFFFF'), 'IND': ('Indiana', 'Pacers', '#002D62', '#FDBB30'),
    'LAC': ('LA', 'Clippers', '#1D428A', '#FFFFFF'), 'LAL': ('Los Angeles', 'Lakers', '#552583', '#FDB927'), 'MEM': ('Memphis', 'Grizzlies', '#12173F', '#F5B112'),
    'MIA': ('Miami', 'Heat', '#98002E', '#F9A01B'), 'MIL': ('Milwaukee', 'Bucks', '#00471B', '#EEE1C6'), 'MIN': ('Minnesota', 'Timberwolves', '#0C2340', '#78BE20'),
    'NO': ('New Orleans', 'Pelicans', '#0C2340', '#C8A86B'), 'NY': ('New York', 'Knicks', '#006BB6', '#F58426'), 'OKC': ('Oklahoma City', 'Thunder', '#007AC1', '#FFFFFF'),
    'ORL': ('Orlando', 'Magic', '#0077C0', '#FFFFFF'), 'PHI': ('Philadelphia', '76ers', '#006BB6', '#FFFFFF'), 'PHX': ('Phoenix', 'Suns', '#1D1160', '#E56020'),
    'POR': ('Portland', 'Trail Blazers', '#000000', '#E03A3E'), 'SAC': ('Sacramento', 'Kings', '#5A2D81', '#FFFFFF'), 'SA': ('San Antonio', 'Spurs', '#000000', '#C4CED4'),
    'TOR': ('Toronto', 'Raptors', '#CE1141', '#FFFFFF'), 'UTAH': ('Utah', 'Jazz', '#002B5C', '#F9A01B'), 'WSH': ('Washington', 'Wizards', '#002B5C', '#FFFFFF'),
}
NHL = {
    'ANA': ('Anaheim', 'Ducks', '#F47A38', '#000000'), 'BOS': ('Boston', 'Bruins', '#FFB81C', '#000000'), 'BUF': ('Buffalo', 'Sabres', '#003087', '#FFB81C'),
    'CAR': ('Carolina', 'Hurricanes', '#CE1126', '#FFFFFF'), 'CBJ': ('Columbus', 'Blue Jackets', '#002654', '#FFFFFF'), 'CGY': ('Calgary', 'Flames', '#C8102E', '#F1BE48'),
    'CHI': ('Chicago', 'Blackhawks', '#CF0A2C', '#FFFFFF'), 'COL': ('Colorado', 'Avalanche', '#6F263D', '#FFFFFF'), 'DAL': ('Dallas', 'Stars', '#006847', '#FFFFFF'),
    'DET': ('Detroit', 'Red Wings', '#CE1126', '#FFFFFF'), 'EDM': ('Edmonton', 'Oilers', '#041E42', '#FF4C00'), 'FLA': ('Florida', 'Panthers', '#041E42', '#C8102E'),
    'LAK': ('Los Angeles', 'Kings', '#111111', '#A2AAAD'), 'MIN': ('Minnesota', 'Wild', '#154734', '#EAAA00'), 'MTL': ('Montréal', 'Canadiens', '#AF1E2D', '#FFFFFF'),
    'NJD': ('New Jersey', 'Devils', '#CE1126', '#FFFFFF'), 'NSH': ('Nashville', 'Predators', '#FFB81C', '#041E42'), 'NYI': ('NY', 'Islanders', '#00539B', '#F47D30'),
    'NYR': ('NY', 'Rangers', '#0038A8', '#FFFFFF'), 'OTT': ('Ottawa', 'Senators', '#C52032', '#FFFFFF'), 'PHI': ('Philadelphia', 'Flyers', '#F74902', '#000000'),
    'PIT': ('Pittsburgh', 'Penguins', '#000000', '#FCB514'), 'SEA': ('Seattle', 'Kraken', '#001628', '#99D9D9'), 'SJS': ('San Jose', 'Sharks', '#006D75', '#FFFFFF'),
    'STL': ('St. Louis', 'Blues', '#002F87', '#FCB514'), 'TBL': ('Tampa Bay', 'Lightning', '#002868', '#FFFFFF'), 'TOR': ('Toronto', 'Maple Leafs', '#00205B', '#FFFFFF'),
    'UTA': ('Utah', 'Mammoth', '#010101', '#6CACE4'), 'VAN': ('Vancouver', 'Canucks', '#00205B', '#00843D'), 'VGK': ('Vegas', 'Golden Knights', '#B4975A', '#333F42'),
    'WPG': ('Winnipeg', 'Jets', '#041E42', '#FFFFFF'), 'WSH': ('Washington', 'Capitals', '#C8102E', '#FFFFFF'),
}
ESPN_NHL = {'NJ': 'NJD', 'SJ': 'SJS', 'TB': 'TBL', 'LA': 'LAK', 'UTAH': 'UTA', 'ARI': 'UTA'}
ESPN_NBA = {'GSW': 'GS', 'NYK': 'NY', 'SAS': 'SA', 'NOP': 'NO', 'UTA': 'UTAH', 'WAS': 'WSH', 'PHO': 'PHX'}


def table(lg):
    src = NBA if lg == 'nba' else NHL
    return {ab: {'abbr': ab, 'city': c, 'nick': n, 'name': f'{c} {n}', 'c1': c1, 'c2': c2} for ab, (c, n, c1, c2) in src.items()}
