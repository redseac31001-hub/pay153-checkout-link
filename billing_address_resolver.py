from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Any

from curl_cffi import requests

_CACHE_PATH = Path(os.getenv("PAY153_BILLING_ADDRESS_CACHE", "/opt/pay153/data/billing_addresses.json"))
_CACHE_LOCK = threading.RLock()
_RESOLVE_LOCK = threading.Lock()
_NOMINATIM_LOCK = threading.Lock()
_LAST_NOMINATIM_AT = 0.0
_LAST_PICK: dict[str, str] = {}

_COUNTRY_NAMES = {
    "BA": "Bosnia and Herzegovina", "US": "United States", "BR": "Brazil",
    "IN": "India", "DE": "Germany", "NL": "Netherlands", "GB": "United Kingdom",
    "FR": "France", "AU": "Australia", "JP": "Japan",
}

_BUILTIN_PUBLIC_ADDRESSES: dict[str, list[dict[str, str]]] = {
    "BA": [
        {"name": "Movenpick Sarajevo", "line1": "Fra Filipa Lastrica 3", "city": "Sarajevo", "state": "", "postal_code": "71000", "country": "BA", "source": "builtin_public"},
        {"name": "Hotel Old Sarajevo", "line1": "Bravadziluk 38", "city": "Sarajevo", "state": "", "postal_code": "71000", "country": "BA", "source": "builtin_public"},
        {"name": "Courtyard Sarajevo", "line1": "Skenderija 1", "city": "Sarajevo", "state": "", "postal_code": "71000", "country": "BA", "source": "builtin_public"},
        {"name": "Hotel Europe", "line1": "Vladislava Skarica 5", "city": "Sarajevo", "state": "", "postal_code": "71000", "country": "BA", "source": "builtin_public"},
        {"name": "Hotel Bosna", "line1": "Kralja Petra I Karadjordjevica 97", "city": "Banja Luka", "state": "", "postal_code": "78000", "country": "BA", "source": "builtin_public"},
        {"name": "Hotel Mellain", "line1": "Aleja Alije Izetbegovica 3", "city": "Tuzla", "state": "", "postal_code": "75000", "country": "BA", "source": "builtin_public"},
        {"name": "Residence Inn Sarajevo", "line1": "Skenderija 43", "city": "Sarajevo", "state": "", "postal_code": "71000", "country": "BA", "source": "builtin_public"},
    ],
    "US": [
        {"name": "The Plaza Hotel", "line1": "768 5th Ave", "city": "New York", "state": "NY", "postal_code": "10019", "country": "US", "source": "builtin_public"},
        {"name": "The New Yorker Hotel", "line1": "481 8th Ave", "city": "New York", "state": "NY", "postal_code": "10001", "country": "US", "source": "builtin_public"},
        {"name": "The Beverly Hills Hotel", "line1": "9641 Sunset Blvd", "city": "Beverly Hills", "state": "CA", "postal_code": "90210", "country": "US", "source": "builtin_public"},
        {"name": "Millennium Biltmore Los Angeles", "line1": "506 S Grand Ave", "city": "Los Angeles", "state": "CA", "postal_code": "90071", "country": "US", "source": "builtin_public"},
        {"name": "Palmer House", "line1": "17 E Monroe St", "city": "Chicago", "state": "IL", "postal_code": "60603", "country": "US", "source": "builtin_public"},
        {"name": "InterContinental Miami", "line1": "100 Chopin Plaza", "city": "Miami", "state": "FL", "postal_code": "33131", "country": "US", "source": "builtin_public"},
        {"name": "Omni Dallas Hotel", "line1": "555 S Lamar St", "city": "Dallas", "state": "TX", "postal_code": "75202", "country": "US", "source": "builtin_public"},
        {"name": "Palace Hotel", "line1": "2 New Montgomery St", "city": "San Francisco", "state": "CA", "postal_code": "94105", "country": "US", "source": "builtin_public"},
        {"name": "Fairmont Olympic Hotel", "line1": "411 University St", "city": "Seattle", "state": "WA", "postal_code": "98101", "country": "US", "source": "builtin_public"},
        {"name": "Willard InterContinental", "line1": "1401 Pennsylvania Ave NW", "city": "Washington", "state": "DC", "postal_code": "20004", "country": "US", "source": "builtin_public"},
    ],
    "GB": [
        {"name": "The Savoy", "line1": "Strand", "city": "London", "state": "", "postal_code": "WC2R 0EZ", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "The Ritz London", "line1": "150 Piccadilly", "city": "London", "state": "", "postal_code": "W1J 9BR", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "The Midland Hotel", "line1": "16 Peter St", "city": "Manchester", "state": "", "postal_code": "M60 2DS", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "The Edwardian Manchester", "line1": "Free Trade Hall, Peter St", "city": "Manchester", "state": "", "postal_code": "M2 5GP", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "The Grand Hotel Birmingham", "line1": "1 Church St", "city": "Birmingham", "state": "", "postal_code": "B3 2FE", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "The Balmoral", "line1": "1 Princes St", "city": "Edinburgh", "state": "", "postal_code": "EH2 2EQ", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "Kimpton Blythswood Square", "line1": "11 Blythswood Square", "city": "Glasgow", "state": "", "postal_code": "G2 4AD", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "Titanic Hotel Liverpool", "line1": "Stanley Dock, Regent Rd", "city": "Liverpool", "state": "", "postal_code": "L3 0AN", "country": "GB", "source": "builtin_public", "type": "office"},
        # 住宅地址 (20条)
        {"name": "Residential London 1", "line1": "123 Oxford Street", "city": "London", "state": "", "postal_code": "W1D 1BS", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential London 2", "line1": "456 Regent Street", "city": "London", "state": "", "postal_code": "W1B 5TG", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential London 3", "line1": "789 Baker Street", "city": "London", "state": "", "postal_code": "NW1 6XE", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential London 4", "line1": "321 King's Road", "city": "London", "state": "", "postal_code": "SW3 5EP", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential London 5", "line1": "654 Piccadilly", "city": "London", "state": "", "postal_code": "W1J 0BJ", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Manchester 1", "line1": "100 Deansgate", "city": "Manchester", "state": "", "postal_code": "M3 2RY", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Manchester 2", "line1": "200 Market Street", "city": "Manchester", "state": "", "postal_code": "M1 1WA", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Birmingham 1", "line1": "50 New Street", "city": "Birmingham", "state": "", "postal_code": "B2 4BQ", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Birmingham 2", "line1": "75 High Street", "city": "Birmingham", "state": "", "postal_code": "B4 7SL", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Edinburgh 1", "line1": "30 Princes Street", "city": "Edinburgh", "state": "", "postal_code": "EH2 2BY", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Edinburgh 2", "line1": "60 George Street", "city": "Edinburgh", "state": "", "postal_code": "EH2 2LR", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Glasgow 1", "line1": "40 Buchanan Street", "city": "Glasgow", "state": "", "postal_code": "G1 3HL", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Glasgow 2", "line1": "80 Sauchiehall Street", "city": "Glasgow", "state": "", "postal_code": "G2 3DH", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Liverpool 1", "line1": "25 Lord Street", "city": "Liverpool", "state": "", "postal_code": "L2 1TA", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Liverpool 2", "line1": "55 Church Street", "city": "Liverpool", "state": "", "postal_code": "L1 1DA", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Leeds 1", "line1": "15 Briggate", "city": "Leeds", "state": "", "postal_code": "LS1 6ER", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Leeds 2", "line1": "45 Boar Lane", "city": "Leeds", "state": "", "postal_code": "LS1 5DA", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Bristol 1", "line1": "20 Park Street", "city": "Bristol", "state": "", "postal_code": "BS1 5JA", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Bristol 2", "line1": "50 Corn Street", "city": "Bristol", "state": "", "postal_code": "BS1 1HT", "country": "GB", "source": "builtin_public", "type": "residential"},
        {"name": "Residential Newcastle 1", "line1": "10 Northumberland Street", "city": "Newcastle", "state": "", "postal_code": "NE1 7DE", "country": "GB", "source": "builtin_public", "type": "residential"},
        # 学校/大学 (15条)
        {"name": "University College London", "line1": "Gower Street", "city": "London", "state": "", "postal_code": "WC1E 6BT", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "Imperial College London", "line1": "South Kensington Campus", "city": "London", "state": "", "postal_code": "SW7 2AZ", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "King's College London", "line1": "Strand", "city": "London", "state": "", "postal_code": "WC2R 2LS", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "London School of Economics", "line1": "Houghton Street", "city": "London", "state": "", "postal_code": "WC2A 2AE", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Oxford", "line1": "Wellington Square", "city": "Oxford", "state": "", "postal_code": "OX1 2JD", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Cambridge", "line1": "The Old Schools", "city": "Cambridge", "state": "", "postal_code": "CB2 1TN", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Manchester", "line1": "Oxford Road", "city": "Manchester", "state": "", "postal_code": "M13 9PL", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Edinburgh", "line1": "Old College, South Bridge", "city": "Edinburgh", "state": "", "postal_code": "EH8 9YL", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Glasgow", "line1": "University Avenue", "city": "Glasgow", "state": "", "postal_code": "G12 8QQ", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Birmingham", "line1": "Edgbaston", "city": "Birmingham", "state": "", "postal_code": "B15 2TT", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Bristol", "line1": "Senate House, Tyndall Avenue", "city": "Bristol", "state": "", "postal_code": "BS8 1TH", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Leeds", "line1": "Woodhouse Lane", "city": "Leeds", "state": "", "postal_code": "LS2 9JT", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "Durham University", "line1": "The Palatine Centre", "city": "Durham", "state": "", "postal_code": "DH1 3LE", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Warwick", "line1": "Coventry", "city": "Coventry", "state": "", "postal_code": "CV4 7AL", "country": "GB", "source": "builtin_public", "type": "school"},
        {"name": "University of Sheffield", "line1": "Western Bank", "city": "Sheffield", "state": "", "postal_code": "S10 2TN", "country": "GB", "source": "builtin_public", "type": "school"},
        # 学生宿舍 (8条)
        {"name": "UCL Student Residence", "line1": "10 Gower Place", "city": "London", "state": "", "postal_code": "WC1E 6BS", "country": "GB", "source": "builtin_public", "type": "student"},
        {"name": "Imperial College Hall", "line1": "Prince's Gardens", "city": "London", "state": "", "postal_code": "SW7 1NA", "country": "GB", "source": "builtin_public", "type": "student"},
        {"name": "King's College Residence", "line1": "Great Dover Street", "city": "London", "state": "", "postal_code": "SE1 4YR", "country": "GB", "source": "builtin_public", "type": "student"},
        {"name": "Oxford Student Hall", "line1": "St Aldate's", "city": "Oxford", "state": "", "postal_code": "OX1 1BX", "country": "GB", "source": "builtin_public", "type": "student"},
        {"name": "Cambridge Student Residence", "line1": "Trinity Street", "city": "Cambridge", "state": "", "postal_code": "CB2 1TQ", "country": "GB", "source": "builtin_public", "type": "student"},
        {"name": "Manchester Student Village", "line1": "99 Upper Brook Street", "city": "Manchester", "state": "", "postal_code": "M13 9TX", "country": "GB", "source": "builtin_public", "type": "student"},
        {"name": "Edinburgh Student Halls", "line1": "18 Holyrood Park Road", "city": "Edinburgh", "state": "", "postal_code": "EH16 5AY", "country": "GB", "source": "builtin_public", "type": "student"},
        {"name": "Birmingham Student Residence", "line1": "Pritchatts Road", "city": "Birmingham", "state": "", "postal_code": "B15 2SA", "country": "GB", "source": "builtin_public", "type": "student"},
        # 办公室/企业 (7条)
        {"name": "Google UK", "line1": "Belgrave House, 76 Buckingham Palace Road", "city": "London", "state": "", "postal_code": "SW1W 9TQ", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "Microsoft UK", "line1": "Thames Valley Park", "city": "Reading", "state": "", "postal_code": "RG6 1WG", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "Apple UK", "line1": "1 Stockley Park", "city": "Uxbridge", "state": "", "postal_code": "UB11 1AA", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "Amazon UK", "line1": "1 Principal Place", "city": "London", "state": "", "postal_code": "EC2A 2FA", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "Facebook UK", "line1": "1 Rathbone Square", "city": "London", "state": "", "postal_code": "W1T 1FB", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "IBM UK", "line1": "76 Upper Ground", "city": "London", "state": "", "postal_code": "SE1 9PZ", "country": "GB", "source": "builtin_public", "type": "office"},
        {"name": "Deloitte UK", "line1": "1 New Street Square", "city": "London", "state": "", "postal_code": "EC4A 3HQ", "country": "GB", "source": "builtin_public", "type": "company"},
    ],
    "TH": [
        # 住宅地址 (20条)
        {"name": "Bangkok Residence 1", "line1": "123 Sukhumvit Road", "city": "Bangkok", "state": "", "postal_code": "10110", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Bangkok Residence 2", "line1": "456 Silom Road", "city": "Bangkok", "state": "", "postal_code": "10500", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Bangkok Residence 3", "line1": "789 Rama IV Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Bangkok Residence 4", "line1": "321 Sathorn Road", "city": "Bangkok", "state": "", "postal_code": "10120", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Bangkok Residence 5", "line1": "654 Ploenchit Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Bangkok Residence 6", "line1": "100 Ratchadamri Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Bangkok Residence 7", "line1": "200 Wireless Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Bangkok Residence 8", "line1": "50 Asok Road", "city": "Bangkok", "state": "", "postal_code": "10110", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Chiang Mai Residence 1", "line1": "30 Nimman Road", "city": "Chiang Mai", "state": "", "postal_code": "50200", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Chiang Mai Residence 2", "line1": "60 Huay Kaew Road", "city": "Chiang Mai", "state": "", "postal_code": "50200", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Phuket Residence 1", "line1": "40 Patong Beach Road", "city": "Phuket", "state": "", "postal_code": "83150", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Phuket Residence 2", "line1": "80 Bangla Road", "city": "Phuket", "state": "", "postal_code": "83150", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Pattaya Residence 1", "line1": "25 Beach Road", "city": "Pattaya", "state": "", "postal_code": "20150", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Pattaya Residence 2", "line1": "55 Second Road", "city": "Pattaya", "state": "", "postal_code": "20150", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Krabi Residence 1", "line1": "15 Ao Nang Beach", "city": "Krabi", "state": "", "postal_code": "81180", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Hua Hin Residence 1", "line1": "20 Petchkasem Road", "city": "Hua Hin", "state": "", "postal_code": "77110", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Samui Residence 1", "line1": "10 Chaweng Beach", "city": "Ko Samui", "state": "", "postal_code": "84320", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Ayutthaya Residence 1", "line1": "5 Naresuan Road", "city": "Ayutthaya", "state": "", "postal_code": "13000", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Khon Kaen Residence 1", "line1": "12 Klang Muang Road", "city": "Khon Kaen", "state": "", "postal_code": "40000", "country": "TH", "source": "builtin_public", "type": "residential"},
        {"name": "Nakhon Ratchasima Residence 1", "line1": "8 Suranarai Road", "city": "Nakhon Ratchasima", "state": "", "postal_code": "30000", "country": "TH", "source": "builtin_public", "type": "residential"},
        # 学校/大学 (15条)
        {"name": "Chulalongkorn University", "line1": "254 Phayathai Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Mahidol University", "line1": "999 Phutthamonthon 4 Road", "city": "Nakhon Pathom", "state": "", "postal_code": "73170", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Thammasat University", "line1": "2 Prachan Road", "city": "Bangkok", "state": "", "postal_code": "10200", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Kasetsart University", "line1": "50 Ngamwongwan Road", "city": "Bangkok", "state": "", "postal_code": "10900", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "King Mongkut's Institute", "line1": "126 Pracha Uthit Road", "city": "Bangkok", "state": "", "postal_code": "10140", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Chiang Mai University", "line1": "239 Huay Kaew Road", "city": "Chiang Mai", "state": "", "postal_code": "50200", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Prince of Songkla University", "line1": "15 Karnjanavanich Road", "city": "Hat Yai", "state": "", "postal_code": "90110", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Khon Kaen University", "line1": "123 Mittraphap Road", "city": "Khon Kaen", "state": "", "postal_code": "40002", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Bangkok University", "line1": "119 Rama IV Road", "city": "Bangkok", "state": "", "postal_code": "10110", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Assumption University", "line1": "592 Ramkhamhaeng 24", "city": "Bangkok", "state": "", "postal_code": "10240", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Silpakorn University", "line1": "31 Na Phra Lan Road", "city": "Bangkok", "state": "", "postal_code": "10200", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Srinakharinwirot University", "line1": "114 Sukhumvit 23", "city": "Bangkok", "state": "", "postal_code": "10110", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Burapha University", "line1": "169 Longhadbangsaen Road", "city": "Chonburi", "state": "", "postal_code": "20131", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Naresuan University", "line1": "99 Moo 9 Phitsanulok", "city": "Phitsanulok", "state": "", "postal_code": "65000", "country": "TH", "source": "builtin_public", "type": "school"},
        {"name": "Suan Dusit University", "line1": "295 Nakhon Ratchasima Road", "city": "Bangkok", "state": "", "postal_code": "10300", "country": "TH", "source": "builtin_public", "type": "school"},
        # 学生宿舍 (8条)
        {"name": "Chula Student Dormitory", "line1": "Phayathai Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "student"},
        {"name": "Mahidol Student Hall", "line1": "Salaya Campus", "city": "Nakhon Pathom", "state": "", "postal_code": "73170", "country": "TH", "source": "builtin_public", "type": "student"},
        {"name": "Thammasat Student Residence", "line1": "Rangsit Campus", "city": "Pathum Thani", "state": "", "postal_code": "12120", "country": "TH", "source": "builtin_public", "type": "student"},
        {"name": "Kasetsart Student Hall", "line1": "Bangkhen Campus", "city": "Bangkok", "state": "", "postal_code": "10900", "country": "TH", "source": "builtin_public", "type": "student"},
        {"name": "Chiang Mai Student Dorm", "line1": "Suthep Campus", "city": "Chiang Mai", "state": "", "postal_code": "50200", "country": "TH", "source": "builtin_public", "type": "student"},
        {"name": "Bangkok Uni Student Hall", "line1": "Rama IV Campus", "city": "Bangkok", "state": "", "postal_code": "10110", "country": "TH", "source": "builtin_public", "type": "student"},
        {"name": "Assumption Student Residence", "line1": "Suvarnabhumi Campus", "city": "Samut Prakan", "state": "", "postal_code": "10540", "country": "TH", "source": "builtin_public", "type": "student"},
        {"name": "Silpakorn Student Dorm", "line1": "Wang Tha Phra Campus", "city": "Bangkok", "state": "", "postal_code": "10600", "country": "TH", "source": "builtin_public", "type": "student"},
        # 办公室/企业 (7条)
        {"name": "Microsoft Thailand", "line1": "2922 New Petchburi Road", "city": "Bangkok", "state": "", "postal_code": "10310", "country": "TH", "source": "builtin_public", "type": "office"},
        {"name": "Google Thailand", "line1": "55 All Seasons Place", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "office"},
        {"name": "Facebook Thailand", "line1": "87 Wireless Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "office"},
        {"name": "Amazon Thailand", "line1": "2 Empire Tower", "city": "Bangkok", "state": "", "postal_code": "10120", "country": "TH", "source": "builtin_public", "type": "office"},
        {"name": "Apple Thailand", "line1": "999 Rama I Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "office"},
        {"name": "IBM Thailand", "line1": "1060 New Petchburi Road", "city": "Bangkok", "state": "", "postal_code": "10310", "country": "TH", "source": "builtin_public", "type": "office"},
        {"name": "Deloitte Thailand", "line1": "999 Rama I Road", "city": "Bangkok", "state": "", "postal_code": "10330", "country": "TH", "source": "builtin_public", "type": "company"},
    ],
    "BR": [
        # 住宅地址 (20条)
        {"name": "São Paulo Residence 1", "line1": "Rua Augusta 1000", "city": "São Paulo", "state": "SP", "postal_code": "01304-000", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "São Paulo Residence 2", "line1": "Avenida Paulista 1500", "city": "São Paulo", "state": "SP", "postal_code": "01310-100", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "São Paulo Residence 3", "line1": "Rua Oscar Freire 500", "city": "São Paulo", "state": "SP", "postal_code": "01426-001", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Rio Residence 1", "line1": "Avenida Atlântica 1000", "city": "Rio de Janeiro", "state": "RJ", "postal_code": "22021-000", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Rio Residence 2", "line1": "Rua Visconde de Pirajá 300", "city": "Rio de Janeiro", "state": "RJ", "postal_code": "22410-000", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Rio Residence 3", "line1": "Avenida Vieira Souto 200", "city": "Rio de Janeiro", "state": "RJ", "postal_code": "22420-000", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Brasília Residence 1", "line1": "SQN 308 Bloco A", "city": "Brasília", "state": "DF", "postal_code": "70747-010", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Brasília Residence 2", "line1": "SQS 116 Bloco B", "city": "Brasília", "state": "DF", "postal_code": "70386-020", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Curitiba Residence 1", "line1": "Rua XV de Novembro 1000", "city": "Curitiba", "state": "PR", "postal_code": "80020-310", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Curitiba Residence 2", "line1": "Avenida Batel 1500", "city": "Curitiba", "state": "PR", "postal_code": "80420-090", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Porto Alegre Residence 1", "line1": "Avenida Independência 800", "city": "Porto Alegre", "state": "RS", "postal_code": "90035-070", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Porto Alegre Residence 2", "line1": "Rua dos Andradas 1500", "city": "Porto Alegre", "state": "RS", "postal_code": "90020-008", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Belo Horizonte Residence 1", "line1": "Avenida Afonso Pena 1000", "city": "Belo Horizonte", "state": "MG", "postal_code": "30130-001", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Belo Horizonte Residence 2", "line1": "Rua da Bahia 1200", "city": "Belo Horizonte", "state": "MG", "postal_code": "30160-011", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Salvador Residence 1", "line1": "Avenida Sete de Setembro 1000", "city": "Salvador", "state": "BA", "postal_code": "40060-001", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Salvador Residence 2", "line1": "Rua Chile 100", "city": "Salvador", "state": "BA", "postal_code": "40020-000", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Fortaleza Residence 1", "line1": "Avenida Beira Mar 3000", "city": "Fortaleza", "state": "CE", "postal_code": "60165-121", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Fortaleza Residence 2", "line1": "Rua Barão de Aracati 500", "city": "Fortaleza", "state": "CE", "postal_code": "60115-080", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Recife Residence 1", "line1": "Avenida Boa Viagem 5000", "city": "Recife", "state": "PE", "postal_code": "51021-000", "country": "BR", "source": "builtin_public", "type": "residential"},
        {"name": "Recife Residence 2", "line1": "Rua do Hospício 200", "city": "Recife", "state": "PE", "postal_code": "50050-110", "country": "BR", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (10条)
        {"name": "USP Student Housing", "line1": "Rua do Matão 1000", "city": "São Paulo", "state": "SP", "postal_code": "05508-090", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UNICAMP Student Housing", "line1": "Cidade Universitária", "city": "Campinas", "state": "SP", "postal_code": "13083-970", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UFRJ Student Housing", "line1": "Ilha do Fundão", "city": "Rio de Janeiro", "state": "RJ", "postal_code": "21941-901", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UnB Student Housing", "line1": "Campus Darcy Ribeiro", "city": "Brasília", "state": "DF", "postal_code": "70910-900", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UFMG Student Housing", "line1": "Campus Pampulha", "city": "Belo Horizonte", "state": "MG", "postal_code": "31270-901", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UFRGS Student Housing", "line1": "Avenida Paulo Gama 110", "city": "Porto Alegre", "state": "RS", "postal_code": "90040-060", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UFPR Student Housing", "line1": "Rua XV de Novembro 1299", "city": "Curitiba", "state": "PR", "postal_code": "80060-000", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UFBA Student Housing", "line1": "Rua Barão de Jeremoabo", "city": "Salvador", "state": "BA", "postal_code": "40170-115", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UFC Student Housing", "line1": "Avenida da Universidade 2853", "city": "Fortaleza", "state": "CE", "postal_code": "60020-181", "country": "BR", "source": "builtin_public", "type": "student"},
        {"name": "UFPE Student Housing", "line1": "Avenida Professor Moraes Rego 1235", "city": "Recife", "state": "PE", "postal_code": "50670-901", "country": "BR", "source": "builtin_public", "type": "student"},
        # 学校/大学 (10条)
        {"name": "Universidade de São Paulo", "line1": "Rua da Reitoria 374", "city": "São Paulo", "state": "SP", "postal_code": "05508-220", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "UNICAMP", "line1": "Cidade Universitária Zeferino Vaz", "city": "Campinas", "state": "SP", "postal_code": "13083-970", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "PUC-Rio", "line1": "Rua Marquês de São Vicente 225", "city": "Rio de Janeiro", "state": "RJ", "postal_code": "22451-900", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "Universidade de Brasília", "line1": "Campus Universitário Darcy Ribeiro", "city": "Brasília", "state": "DF", "postal_code": "70910-900", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "UFMG", "line1": "Avenida Antônio Carlos 6627", "city": "Belo Horizonte", "state": "MG", "postal_code": "31270-901", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "UFRGS", "line1": "Avenida Paulo Gama 110", "city": "Porto Alegre", "state": "RS", "postal_code": "90040-060", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "PUC-PR", "line1": "Rua Imaculada Conceição 1155", "city": "Curitiba", "state": "PR", "postal_code": "80215-901", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "UFBA", "line1": "Rua Augusto Viana", "city": "Salvador", "state": "BA", "postal_code": "40110-909", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "UFC", "line1": "Avenida da Universidade 2853", "city": "Fortaleza", "state": "CE", "postal_code": "60020-181", "country": "BR", "source": "builtin_public", "type": "school"},
        {"name": "UFPE", "line1": "Avenida Professor Moraes Rego 1235", "city": "Recife", "state": "PE", "postal_code": "50670-901", "country": "BR", "source": "builtin_public", "type": "school"},
        # 办公室 (5条)
        {"name": "Google Brazil", "line1": "Avenida Brigadeiro Faria Lima 3729", "city": "São Paulo", "state": "SP", "postal_code": "04538-133", "country": "BR", "source": "builtin_public", "type": "office"},
        {"name": "Microsoft Brazil", "line1": "Avenida das Nações Unidas 12901", "city": "São Paulo", "state": "SP", "postal_code": "04578-000", "country": "BR", "source": "builtin_public", "type": "office"},
        {"name": "Amazon Brazil", "line1": "Avenida Presidente Juscelino Kubitschek 2041", "city": "São Paulo", "state": "SP", "postal_code": "04543-011", "country": "BR", "source": "builtin_public", "type": "office"},
        {"name": "IBM Brazil", "line1": "Rua Tutóia 1157", "city": "São Paulo", "state": "SP", "postal_code": "04007-900", "country": "BR", "source": "builtin_public", "type": "office"},
        {"name": "Oracle Brazil", "line1": "Avenida Dr. Chucri Zaidan 940", "city": "São Paulo", "state": "SP", "postal_code": "04583-110", "country": "BR", "source": "builtin_public", "type": "office"},
        # 企业 (5条)
        {"name": "Petrobras", "line1": "Avenida República do Chile 65", "city": "Rio de Janeiro", "state": "RJ", "postal_code": "20031-912", "country": "BR", "source": "builtin_public", "type": "company"},
        {"name": "Vale", "line1": "Avenida Graça Aranha 26", "city": "Rio de Janeiro", "state": "RJ", "postal_code": "20030-900", "country": "BR", "source": "builtin_public", "type": "company"},
        {"name": "Itaú Unibanco", "line1": "Praça Alfredo Egydio de Souza Aranha 100", "city": "São Paulo", "state": "SP", "postal_code": "04344-902", "country": "BR", "source": "builtin_public", "type": "company"},
        {"name": "Bradesco", "line1": "Cidade de Deus", "city": "Osasco", "state": "SP", "postal_code": "06029-900", "country": "BR", "source": "builtin_public", "type": "company"},
        {"name": "Ambev", "line1": "Rua Dr. Renato Paes de Barros 1017", "city": "São Paulo", "state": "SP", "postal_code": "04530-001", "country": "BR", "source": "builtin_public", "type": "company"},
    ],
    "DE": [
        # 住宅地址 (20条)
        {"name": "Berlin Residence 1", "line1": "Unter den Linden 10", "city": "Berlin", "state": "", "postal_code": "10117", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Berlin Residence 2", "line1": "Kurfürstendamm 100", "city": "Berlin", "state": "", "postal_code": "10709", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Berlin Residence 3", "line1": "Friedrichstraße 50", "city": "Berlin", "state": "", "postal_code": "10117", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Munich Residence 1", "line1": "Maximilianstraße 20", "city": "Munich", "state": "", "postal_code": "80539", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Munich Residence 2", "line1": "Leopoldstraße 100", "city": "Munich", "state": "", "postal_code": "80802", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Munich Residence 3", "line1": "Sendlinger Straße 50", "city": "Munich", "state": "", "postal_code": "80331", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Hamburg Residence 1", "line1": "Jungfernstieg 20", "city": "Hamburg", "state": "", "postal_code": "20354", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Hamburg Residence 2", "line1": "Mönckebergstraße 10", "city": "Hamburg", "state": "", "postal_code": "20095", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Frankfurt Residence 1", "line1": "Zeil 100", "city": "Frankfurt", "state": "", "postal_code": "60313", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Frankfurt Residence 2", "line1": "Kaiserstraße 50", "city": "Frankfurt", "state": "", "postal_code": "60329", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Cologne Residence 1", "line1": "Hohe Straße 80", "city": "Cologne", "state": "", "postal_code": "50667", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Cologne Residence 2", "line1": "Schildergasse 100", "city": "Cologne", "state": "", "postal_code": "50667", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Stuttgart Residence 1", "line1": "Königstraße 50", "city": "Stuttgart", "state": "", "postal_code": "70173", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Stuttgart Residence 2", "line1": "Theodor-Heuss-Straße 20", "city": "Stuttgart", "state": "", "postal_code": "70174", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Düsseldorf Residence 1", "line1": "Königsallee 100", "city": "Düsseldorf", "state": "", "postal_code": "40212", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Düsseldorf Residence 2", "line1": "Heinrich-Heine-Allee 50", "city": "Düsseldorf", "state": "", "postal_code": "40213", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Dortmund Residence 1", "line1": "Westenhellweg 100", "city": "Dortmund", "state": "", "postal_code": "44137", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Dortmund Residence 2", "line1": "Kampstraße 50", "city": "Dortmund", "state": "", "postal_code": "44137", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Essen Residence 1", "line1": "Kettwiger Straße 50", "city": "Essen", "state": "", "postal_code": "45127", "country": "DE", "source": "builtin_public", "type": "residential"},
        {"name": "Essen Residence 2", "line1": "Limbecker Platz 1", "city": "Essen", "state": "", "postal_code": "45127", "country": "DE", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (10条)
        {"name": "TU Berlin Student Housing", "line1": "Straße des 17. Juni 135", "city": "Berlin", "state": "", "postal_code": "10623", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "Humboldt University Housing", "line1": "Unter den Linden 6", "city": "Berlin", "state": "", "postal_code": "10099", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "LMU Munich Student Housing", "line1": "Geschwister-Scholl-Platz 1", "city": "Munich", "state": "", "postal_code": "80539", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "TU Munich Student Housing", "line1": "Arcisstraße 21", "city": "Munich", "state": "", "postal_code": "80333", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "University of Hamburg Housing", "line1": "Edmund-Siemers-Allee 1", "city": "Hamburg", "state": "", "postal_code": "20146", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "Goethe University Housing", "line1": "Theodor-W.-Adorno-Platz 1", "city": "Frankfurt", "state": "", "postal_code": "60323", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "University of Cologne Housing", "line1": "Albertus-Magnus-Platz", "city": "Cologne", "state": "", "postal_code": "50923", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "University of Stuttgart Housing", "line1": "Keplerstraße 7", "city": "Stuttgart", "state": "", "postal_code": "70174", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "Heinrich Heine University Housing", "line1": "Universitätsstraße 1", "city": "Düsseldorf", "state": "", "postal_code": "40225", "country": "DE", "source": "builtin_public", "type": "student"},
        {"name": "TU Dortmund Student Housing", "line1": "August-Schmidt-Straße 1", "city": "Dortmund", "state": "", "postal_code": "44227", "country": "DE", "source": "builtin_public", "type": "student"},
        # 学校/大学 (10条)
        {"name": "Technical University of Berlin", "line1": "Straße des 17. Juni 135", "city": "Berlin", "state": "", "postal_code": "10623", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "Humboldt University of Berlin", "line1": "Unter den Linden 6", "city": "Berlin", "state": "", "postal_code": "10099", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "Ludwig Maximilian University", "line1": "Geschwister-Scholl-Platz 1", "city": "Munich", "state": "", "postal_code": "80539", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "Technical University of Munich", "line1": "Arcisstraße 21", "city": "Munich", "state": "", "postal_code": "80333", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "University of Hamburg", "line1": "Edmund-Siemers-Allee 1", "city": "Hamburg", "state": "", "postal_code": "20146", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "Goethe University Frankfurt", "line1": "Theodor-W.-Adorno-Platz 1", "city": "Frankfurt", "state": "", "postal_code": "60323", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "University of Cologne", "line1": "Albertus-Magnus-Platz", "city": "Cologne", "state": "", "postal_code": "50923", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "University of Stuttgart", "line1": "Keplerstraße 7", "city": "Stuttgart", "state": "", "postal_code": "70174", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "Heinrich Heine University", "line1": "Universitätsstraße 1", "city": "Düsseldorf", "state": "", "postal_code": "40225", "country": "DE", "source": "builtin_public", "type": "school"},
        {"name": "TU Dortmund University", "line1": "August-Schmidt-Straße 1", "city": "Dortmund", "state": "", "postal_code": "44227", "country": "DE", "source": "builtin_public", "type": "school"},
        # 办公室 (5条)
        {"name": "Google Germany", "line1": "Tucholskystraße 2", "city": "Berlin", "state": "", "postal_code": "10117", "country": "DE", "source": "builtin_public", "type": "office"},
        {"name": "Microsoft Germany", "line1": "Walter-Gropius-Straße 5", "city": "Munich", "state": "", "postal_code": "80807", "country": "DE", "source": "builtin_public", "type": "office"},
        {"name": "Amazon Germany", "line1": "Krausenstraße 38", "city": "Berlin", "state": "", "postal_code": "10117", "country": "DE", "source": "builtin_public", "type": "office"},
        {"name": "SAP Germany", "line1": "Dietmar-Hopp-Allee 16", "city": "Walldorf", "state": "", "postal_code": "69190", "country": "DE", "source": "builtin_public", "type": "office"},
        {"name": "Siemens Germany", "line1": "Werner-von-Siemens-Straße 1", "city": "Munich", "state": "", "postal_code": "80333", "country": "DE", "source": "builtin_public", "type": "office"},
        # 企业 (5条)
        {"name": "Deutsche Bank", "line1": "Taunusanlage 12", "city": "Frankfurt", "state": "", "postal_code": "60325", "country": "DE", "source": "builtin_public", "type": "company"},
        {"name": "Volkswagen AG", "line1": "Berliner Ring 2", "city": "Wolfsburg", "state": "", "postal_code": "38440", "country": "DE", "source": "builtin_public", "type": "company"},
        {"name": "BMW Group", "line1": "Petuelring 130", "city": "Munich", "state": "", "postal_code": "80788", "country": "DE", "source": "builtin_public", "type": "company"},
        {"name": "Allianz SE", "line1": "Königinstraße 28", "city": "Munich", "state": "", "postal_code": "80802", "country": "DE", "source": "builtin_public", "type": "company"},
        {"name": "BASF SE", "line1": "Carl-Bosch-Straße 38", "city": "Ludwigshafen", "state": "", "postal_code": "67056", "country": "DE", "source": "builtin_public", "type": "company"},
    ],
    "NL": [
        # 住宅地址 (20条)
        {"name": "Amsterdam Residence 1", "line1": "Damrak 100", "city": "Amsterdam", "state": "", "postal_code": "1012 LP", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Amsterdam Residence 2", "line1": "Kalverstraat 50", "city": "Amsterdam", "state": "", "postal_code": "1012 PB", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Amsterdam Residence 3", "line1": "Leidsestraat 100", "city": "Amsterdam", "state": "", "postal_code": "1017 PB", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Rotterdam Residence 1", "line1": "Coolsingel 100", "city": "Rotterdam", "state": "", "postal_code": "3012 AG", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Rotterdam Residence 2", "line1": "Lijnbaan 50", "city": "Rotterdam", "state": "", "postal_code": "3012 ER", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "The Hague Residence 1", "line1": "Lange Voorhout 50", "city": "The Hague", "state": "", "postal_code": "2514 EG", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "The Hague Residence 2", "line1": "Spui 100", "city": "The Hague", "state": "", "postal_code": "2511 BV", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Utrecht Residence 1", "line1": "Oudegracht 200", "city": "Utrecht", "state": "", "postal_code": "3511 NV", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Utrecht Residence 2", "line1": "Vredenburg 50", "city": "Utrecht", "state": "", "postal_code": "3511 BC", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Eindhoven Residence 1", "line1": "Rechtestraat 50", "city": "Eindhoven", "state": "", "postal_code": "5611 GP", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Eindhoven Residence 2", "line1": "Stationsweg 100", "city": "Eindhoven", "state": "", "postal_code": "5611 AB", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Groningen Residence 1", "line1": "Grote Markt 50", "city": "Groningen", "state": "", "postal_code": "9711 LV", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Groningen Residence 2", "line1": "Herestraat 100", "city": "Groningen", "state": "", "postal_code": "9711 LM", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Maastricht Residence 1", "line1": "Vrijthof 50", "city": "Maastricht", "state": "", "postal_code": "6211 LE", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Maastricht Residence 2", "line1": "Grote Staat 100", "city": "Maastricht", "state": "", "postal_code": "6211 CV", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Leiden Residence 1", "line1": "Breestraat 100", "city": "Leiden", "state": "", "postal_code": "2311 CS", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Leiden Residence 2", "line1": "Haarlemmerstraat 50", "city": "Leiden", "state": "", "postal_code": "2312 GC", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Delft Residence 1", "line1": "Markt 50", "city": "Delft", "state": "", "postal_code": "2611 GS", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Delft Residence 2", "line1": "Hippolytusbuurt 100", "city": "Delft", "state": "", "postal_code": "2611 HM", "country": "NL", "source": "builtin_public", "type": "residential"},
        {"name": "Nijmegen Residence 1", "line1": "Grote Markt 50", "city": "Nijmegen", "state": "", "postal_code": "6511 KB", "country": "NL", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (10条)
        {"name": "UvA Student Housing", "line1": "Spui 21", "city": "Amsterdam", "state": "", "postal_code": "1012 WX", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "VU Amsterdam Student Housing", "line1": "De Boelelaan 1105", "city": "Amsterdam", "state": "", "postal_code": "1081 HV", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "EUR Student Housing", "line1": "Burgemeester Oudlaan 50", "city": "Rotterdam", "state": "", "postal_code": "3062 PA", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "Leiden University Housing", "line1": "Rapenburg 70", "city": "Leiden", "state": "", "postal_code": "2311 EZ", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "Utrecht University Housing", "line1": "Heidelberglaan 8", "city": "Utrecht", "state": "", "postal_code": "3584 CS", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "TU Delft Student Housing", "line1": "Mekelweg 5", "city": "Delft", "state": "", "postal_code": "2628 CC", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "TU Eindhoven Student Housing", "line1": "Den Dolech 2", "city": "Eindhoven", "state": "", "postal_code": "5612 AZ", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "University of Groningen Housing", "line1": "Broerstraat 5", "city": "Groningen", "state": "", "postal_code": "9712 CP", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "Maastricht University Housing", "line1": "Minderbroedersberg 4-6", "city": "Maastricht", "state": "", "postal_code": "6211 LK", "country": "NL", "source": "builtin_public", "type": "student"},
        {"name": "Radboud University Housing", "line1": "Comeniuslaan 4", "city": "Nijmegen", "state": "", "postal_code": "6525 HP", "country": "NL", "source": "builtin_public", "type": "student"},
        # 学校/大学 (10条)
        {"name": "University of Amsterdam", "line1": "Spui 21", "city": "Amsterdam", "state": "", "postal_code": "1012 WX", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "VU Amsterdam", "line1": "De Boelelaan 1105", "city": "Amsterdam", "state": "", "postal_code": "1081 HV", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "Erasmus University Rotterdam", "line1": "Burgemeester Oudlaan 50", "city": "Rotterdam", "state": "", "postal_code": "3062 PA", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "Leiden University", "line1": "Rapenburg 70", "city": "Leiden", "state": "", "postal_code": "2311 EZ", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "Utrecht University", "line1": "Heidelberglaan 8", "city": "Utrecht", "state": "", "postal_code": "3584 CS", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "Delft University of Technology", "line1": "Mekelweg 5", "city": "Delft", "state": "", "postal_code": "2628 CC", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "Eindhoven University of Technology", "line1": "Den Dolech 2", "city": "Eindhoven", "state": "", "postal_code": "5612 AZ", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "University of Groningen", "line1": "Broerstraat 5", "city": "Groningen", "state": "", "postal_code": "9712 CP", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "Maastricht University", "line1": "Minderbroedersberg 4-6", "city": "Maastricht", "state": "", "postal_code": "6211 LK", "country": "NL", "source": "builtin_public", "type": "school"},
        {"name": "Radboud University", "line1": "Comeniuslaan 4", "city": "Nijmegen", "state": "", "postal_code": "6525 HP", "country": "NL", "source": "builtin_public", "type": "school"},
        # 办公室 (5条)
        {"name": "Google Netherlands", "line1": "Claude Debussylaan 34", "city": "Amsterdam", "state": "", "postal_code": "1082 MD", "country": "NL", "source": "builtin_public", "type": "office"},
        {"name": "Microsoft Netherlands", "line1": "Evert van de Beekstraat 354", "city": "Schiphol", "state": "", "postal_code": "1118 CZ", "country": "NL", "source": "builtin_public", "type": "office"},
        {"name": "Booking.com", "line1": "Herengracht 597", "city": "Amsterdam", "state": "", "postal_code": "1017 CE", "country": "NL", "source": "builtin_public", "type": "office"},
        {"name": "Philips Netherlands", "line1": "Amstelplein 2", "city": "Amsterdam", "state": "", "postal_code": "1096 BC", "country": "NL", "source": "builtin_public", "type": "office"},
        {"name": "Shell Netherlands", "line1": "Carel van Bylandtlaan 16", "city": "The Hague", "state": "", "postal_code": "2596 HR", "country": "NL", "source": "builtin_public", "type": "office"},
        # 企业 (5条)
        {"name": "ING Group", "line1": "Bijlmerplein 888", "city": "Amsterdam", "state": "", "postal_code": "1102 MG", "country": "NL", "source": "builtin_public", "type": "company"},
        {"name": "ABN AMRO", "line1": "Gustav Mahlerlaan 10", "city": "Amsterdam", "state": "", "postal_code": "1082 PP", "country": "NL", "source": "builtin_public", "type": "company"},
        {"name": "Unilever Netherlands", "line1": "Weena 455", "city": "Rotterdam", "state": "", "postal_code": "3013 AL", "country": "NL", "source": "builtin_public", "type": "company"},
        {"name": "Heineken", "line1": "Tweede Weteringplantsoen 21", "city": "Amsterdam", "state": "", "postal_code": "1017 ZD", "country": "NL", "source": "builtin_public", "type": "company"},
        {"name": "ASML", "line1": "De Run 6501", "city": "Veldhoven", "state": "", "postal_code": "5504 DR", "country": "NL", "source": "builtin_public", "type": "company"},
    ],
    "ID": [
        # 印尼 - 住宅地址 (15条)
        {"name": "Jakarta Residence 1", "line1": "Jl. Sudirman 123", "city": "Jakarta", "state": "", "postal_code": "10220", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Jakarta Residence 2", "line1": "Jl. Thamrin 456", "city": "Jakarta", "state": "", "postal_code": "10230", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Jakarta Residence 3", "line1": "Jl. Gatot Subroto 789", "city": "Jakarta", "state": "", "postal_code": "12930", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Jakarta Residence 4", "line1": "Jl. Rasuna Said 321", "city": "Jakarta", "state": "", "postal_code": "12940", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Jakarta Residence 5", "line1": "Jl. HR Rasuna Said 654", "city": "Jakarta", "state": "", "postal_code": "12950", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Surabaya Residence 1", "line1": "Jl. Raya Darmo 100", "city": "Surabaya", "state": "", "postal_code": "60264", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Surabaya Residence 2", "line1": "Jl. Pemuda 200", "city": "Surabaya", "state": "", "postal_code": "60271", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Bandung Residence 1", "line1": "Jl. Asia Afrika 50", "city": "Bandung", "state": "", "postal_code": "40111", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Bandung Residence 2", "line1": "Jl. Dago 80", "city": "Bandung", "state": "", "postal_code": "40135", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Bali Residence 1", "line1": "Jl. Sunset Road 30", "city": "Denpasar", "state": "", "postal_code": "80361", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Bali Residence 2", "line1": "Jl. Legian 60", "city": "Kuta", "state": "", "postal_code": "80361", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Yogyakarta Residence 1", "line1": "Jl. Malioboro 40", "city": "Yogyakarta", "state": "", "postal_code": "55271", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Yogyakarta Residence 2", "line1": "Jl. Solo 80", "city": "Yogyakarta", "state": "", "postal_code": "55284", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Medan Residence 1", "line1": "Jl. Sisingamangaraja 25", "city": "Medan", "state": "", "postal_code": "20212", "country": "ID", "source": "builtin_public", "type": "residential"},
        {"name": "Semarang Residence 1", "line1": "Jl. Pemuda 15", "city": "Semarang", "state": "", "postal_code": "50132", "country": "ID", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (8条)
        {"name": "UI Student Housing", "line1": "Kampus UI Depok", "city": "Depok", "state": "", "postal_code": "16424", "country": "ID", "source": "builtin_public", "type": "student"},
        {"name": "ITB Student Housing", "line1": "Jl. Ganesha 10", "city": "Bandung", "state": "", "postal_code": "40132", "country": "ID", "source": "builtin_public", "type": "student"},
        {"name": "UGM Student Housing", "line1": "Bulaksumur", "city": "Yogyakarta", "state": "", "postal_code": "55281", "country": "ID", "source": "builtin_public", "type": "student"},
        {"name": "ITS Student Housing", "line1": "Kampus ITS Sukolilo", "city": "Surabaya", "state": "", "postal_code": "60111", "country": "ID", "source": "builtin_public", "type": "student"},
        {"name": "Unair Student Housing", "line1": "Jl. Airlangga 4-6", "city": "Surabaya", "state": "", "postal_code": "60286", "country": "ID", "source": "builtin_public", "type": "student"},
        {"name": "Undip Student Housing", "line1": "Jl. Prof. Sudarto", "city": "Semarang", "state": "", "postal_code": "50275", "country": "ID", "source": "builtin_public", "type": "student"},
        {"name": "USU Student Housing", "line1": "Jl. Dr. Mansyur 9", "city": "Medan", "state": "", "postal_code": "20155", "country": "ID", "source": "builtin_public", "type": "student"},
        {"name": "Unpad Student Housing", "line1": "Jl. Raya Bandung-Sumedang", "city": "Jatinangor", "state": "", "postal_code": "45363", "country": "ID", "source": "builtin_public", "type": "student"},
        # 学校/大学 (10条)
        {"name": "University of Indonesia", "line1": "Kampus UI Depok", "city": "Depok", "state": "", "postal_code": "16424", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Bandung Institute of Technology", "line1": "Jl. Ganesha 10", "city": "Bandung", "state": "", "postal_code": "40132", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Gadjah Mada University", "line1": "Bulaksumur", "city": "Yogyakarta", "state": "", "postal_code": "55281", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Institut Teknologi Sepuluh Nopember", "line1": "Kampus ITS Sukolilo", "city": "Surabaya", "state": "", "postal_code": "60111", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Airlangga University", "line1": "Jl. Airlangga 4-6", "city": "Surabaya", "state": "", "postal_code": "60286", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Diponegoro University", "line1": "Jl. Prof. Sudarto", "city": "Semarang", "state": "", "postal_code": "50275", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Sumatera Utara University", "line1": "Jl. Dr. Mansyur 9", "city": "Medan", "state": "", "postal_code": "20155", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Padjadjaran University", "line1": "Jl. Raya Bandung-Sumedang", "city": "Jatinangor", "state": "", "postal_code": "45363", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Binus University", "line1": "Jl. Kebon Jeruk Raya 27", "city": "Jakarta", "state": "", "postal_code": "11530", "country": "ID", "source": "builtin_public", "type": "school"},
        {"name": "Trisakti University", "line1": "Jl. Kyai Tapa 1", "city": "Jakarta", "state": "", "postal_code": "11440", "country": "ID", "source": "builtin_public", "type": "school"},
        # 办公室/企业 (7条)
        {"name": "Gojek", "line1": "Jl. Iskandarsyah II 7", "city": "Jakarta", "state": "", "postal_code": "12160", "country": "ID", "source": "builtin_public", "type": "company"},
        {"name": "Tokopedia", "line1": "Wisma 77 Tower 2", "city": "Jakarta", "state": "", "postal_code": "12940", "country": "ID", "source": "builtin_public", "type": "company"},
        {"name": "Bukalapak", "line1": "Jl. Prof. Dr. Satrio", "city": "Jakarta", "state": "", "postal_code": "12940", "country": "ID", "source": "builtin_public", "type": "company"},
        {"name": "Traveloka", "line1": "Jl. Mega Kuningan Barat III", "city": "Jakarta", "state": "", "postal_code": "12950", "country": "ID", "source": "builtin_public", "type": "company"},
        {"name": "Bank Central Asia", "line1": "Menara BCA", "city": "Jakarta", "state": "", "postal_code": "10310", "country": "ID", "source": "builtin_public", "type": "company"},
        {"name": "Bank Mandiri", "line1": "Jl. Gatot Subroto", "city": "Jakarta", "state": "", "postal_code": "12930", "country": "ID", "source": "builtin_public", "type": "company"},
        {"name": "Telkom Indonesia", "line1": "Jl. Japati 1", "city": "Bandung", "state": "", "postal_code": "40133", "country": "ID", "source": "builtin_public", "type": "company"},
    ],
    "MY": [
        # 马来西亚 - 住宅地址 (15条)
        {"name": "Kuala Lumpur Residence 1", "line1": "Jalan Bukit Bintang 123", "city": "Kuala Lumpur", "state": "", "postal_code": "55100", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Kuala Lumpur Residence 2", "line1": "Jalan Raja Chulan 456", "city": "Kuala Lumpur", "state": "", "postal_code": "50200", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Kuala Lumpur Residence 3", "line1": "Jalan Ampang 789", "city": "Kuala Lumpur", "state": "", "postal_code": "50450", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Kuala Lumpur Residence 4", "line1": "Jalan Tun Razak 321", "city": "Kuala Lumpur", "state": "", "postal_code": "50400", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Kuala Lumpur Residence 5", "line1": "Jalan Sultan Ismail 654", "city": "Kuala Lumpur", "state": "", "postal_code": "50250", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Petaling Jaya Residence 1", "line1": "Jalan PJ 100", "city": "Petaling Jaya", "state": "", "postal_code": "46000", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Petaling Jaya Residence 2", "line1": "Jalan SS2 200", "city": "Petaling Jaya", "state": "", "postal_code": "47300", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Penang Residence 1", "line1": "Jalan Penang 50", "city": "George Town", "state": "", "postal_code": "10000", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Penang Residence 2", "line1": "Jalan Macalister 80", "city": "George Town", "state": "", "postal_code": "10400", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Johor Bahru Residence 1", "line1": "Jalan Wong Ah Fook 30", "city": "Johor Bahru", "state": "", "postal_code": "80000", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Johor Bahru Residence 2", "line1": "Jalan Trus 60", "city": "Johor Bahru", "state": "", "postal_code": "80000", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Ipoh Residence 1", "line1": "Jalan Sultan Idris Shah 40", "city": "Ipoh", "state": "", "postal_code": "30000", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Malacca Residence 1", "line1": "Jalan Hang Tuah 25", "city": "Malacca", "state": "", "postal_code": "75200", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Shah Alam Residence 1", "line1": "Jalan Plumbum 15", "city": "Shah Alam", "state": "", "postal_code": "40000", "country": "MY", "source": "builtin_public", "type": "residential"},
        {"name": "Putrajaya Residence 1", "line1": "Persiaran Perdana 10", "city": "Putrajaya", "state": "", "postal_code": "62000", "country": "MY", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (8条)
        {"name": "UM Student Housing", "line1": "University of Malaya", "city": "Kuala Lumpur", "state": "", "postal_code": "50603", "country": "MY", "source": "builtin_public", "type": "student"},
        {"name": "UKM Student Housing", "line1": "Universiti Kebangsaan Malaysia", "city": "Bangi", "state": "", "postal_code": "43600", "country": "MY", "source": "builtin_public", "type": "student"},
        {"name": "UPM Student Housing", "line1": "Universiti Putra Malaysia", "city": "Serdang", "state": "", "postal_code": "43400", "country": "MY", "source": "builtin_public", "type": "student"},
        {"name": "USM Student Housing", "line1": "Universiti Sains Malaysia", "city": "Penang", "state": "", "postal_code": "11800", "country": "MY", "source": "builtin_public", "type": "student"},
        {"name": "UTM Student Housing", "line1": "Universiti Teknologi Malaysia", "city": "Skudai", "state": "", "postal_code": "81310", "country": "MY", "source": "builtin_public", "type": "student"},
        {"name": "Taylor's Student Housing", "line1": "Taylor's University", "city": "Subang Jaya", "state": "", "postal_code": "47500", "country": "MY", "source": "builtin_public", "type": "student"},
        {"name": "Sunway Student Housing", "line1": "Sunway University", "city": "Petaling Jaya", "state": "", "postal_code": "47500", "country": "MY", "source": "builtin_public", "type": "student"},
        {"name": "MMU Student Housing", "line1": "Multimedia University", "city": "Cyberjaya", "state": "", "postal_code": "63100", "country": "MY", "source": "builtin_public", "type": "student"},
    ],
    "SG": [
        # 新加坡 - 住宅地址 (15条)
        {"name": "Singapore Residence 1", "line1": "1 Orchard Road", "city": "Singapore", "state": "", "postal_code": "238824", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 2", "line1": "100 Beach Road", "city": "Singapore", "state": "", "postal_code": "189702", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 3", "line1": "50 Raffles Place", "city": "Singapore", "state": "", "postal_code": "048623", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 4", "line1": "200 Victoria Street", "city": "Singapore", "state": "", "postal_code": "188021", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 5", "line1": "300 Tanglin Road", "city": "Singapore", "state": "", "postal_code": "247922", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 6", "line1": "10 Marina Boulevard", "city": "Singapore", "state": "", "postal_code": "018983", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 7", "line1": "20 Collyer Quay", "city": "Singapore", "state": "", "postal_code": "049319", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 8", "line1": "30 Shenton Way", "city": "Singapore", "state": "", "postal_code": "068803", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 9", "line1": "40 Robinson Road", "city": "Singapore", "state": "", "postal_code": "068908", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 10", "line1": "50 Changi Business Park", "city": "Singapore", "state": "", "postal_code": "486564", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 11", "line1": "60 Paya Lebar Road", "city": "Singapore", "state": "", "postal_code": "409051", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 12", "line1": "70 Bukit Timah Road", "city": "Singapore", "state": "", "postal_code": "229832", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 13", "line1": "80 Clementi Road", "city": "Singapore", "state": "", "postal_code": "129805", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 14", "line1": "90 Jurong East Street", "city": "Singapore", "state": "", "postal_code": "609601", "country": "SG", "source": "builtin_public", "type": "residential"},
        {"name": "Singapore Residence 15", "line1": "100 Tampines Avenue", "city": "Singapore", "state": "", "postal_code": "528764", "country": "SG", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (8条)
        {"name": "NUS Student Housing", "line1": "21 Lower Kent Ridge Road", "city": "Singapore", "state": "", "postal_code": "119077", "country": "SG", "source": "builtin_public", "type": "student"},
        {"name": "NTU Student Housing", "line1": "50 Nanyang Avenue", "city": "Singapore", "state": "", "postal_code": "639798", "country": "SG", "source": "builtin_public", "type": "student"},
        {"name": "SMU Student Housing", "line1": "81 Victoria Street", "city": "Singapore", "state": "", "postal_code": "188065", "country": "SG", "source": "builtin_public", "type": "student"},
        {"name": "SUTD Student Housing", "line1": "8 Somapah Road", "city": "Singapore", "state": "", "postal_code": "487372", "country": "SG", "source": "builtin_public", "type": "student"},
        {"name": "SIT Student Housing", "line1": "10 Dover Drive", "city": "Singapore", "state": "", "postal_code": "138683", "country": "SG", "source": "builtin_public", "type": "student"},
        {"name": "SUSS Student Housing", "line1": "463 Clementi Road", "city": "Singapore", "state": "", "postal_code": "599494", "country": "SG", "source": "builtin_public", "type": "student"},
        {"name": "LASALLE Student Housing", "line1": "1 McNally Street", "city": "Singapore", "state": "", "postal_code": "187940", "country": "SG", "source": "builtin_public", "type": "student"},
        {"name": "NAFA Student Housing", "line1": "80 Bencoolen Street", "city": "Singapore", "state": "", "postal_code": "189655", "country": "SG", "source": "builtin_public", "type": "student"},
        # 学校/大学 (7条)
        {"name": "National University of Singapore", "line1": "21 Lower Kent Ridge Road", "city": "Singapore", "state": "", "postal_code": "119077", "country": "SG", "source": "builtin_public", "type": "school"},
        {"name": "Nanyang Technological University", "line1": "50 Nanyang Avenue", "city": "Singapore", "state": "", "postal_code": "639798", "country": "SG", "source": "builtin_public", "type": "school"},
        {"name": "Singapore Management University", "line1": "81 Victoria Street", "city": "Singapore", "state": "", "postal_code": "188065", "country": "SG", "source": "builtin_public", "type": "school"},
        {"name": "Singapore University of Technology and Design", "line1": "8 Somapah Road", "city": "Singapore", "state": "", "postal_code": "487372", "country": "SG", "source": "builtin_public", "type": "school"},
        {"name": "Singapore Institute of Technology", "line1": "10 Dover Drive", "city": "Singapore", "state": "", "postal_code": "138683", "country": "SG", "source": "builtin_public", "type": "school"},
        {"name": "Singapore University of Social Sciences", "line1": "463 Clementi Road", "city": "Singapore", "state": "", "postal_code": "599494", "country": "SG", "source": "builtin_public", "type": "school"},
        {"name": "Yale-NUS College", "line1": "16 College Avenue West", "city": "Singapore", "state": "", "postal_code": "138527", "country": "SG", "source": "builtin_public", "type": "school"},
        # 办公室/企业 (10条)
        {"name": "Grab", "line1": "3 Media Close", "city": "Singapore", "state": "", "postal_code": "138498", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "Shopee", "line1": "5 Science Park Drive", "city": "Singapore", "state": "", "postal_code": "118265", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "Sea Group", "line1": "1 Fusionopolis Place", "city": "Singapore", "state": "", "postal_code": "138522", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "DBS Bank", "line1": "12 Marina Boulevard", "city": "Singapore", "state": "", "postal_code": "018982", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "OCBC Bank", "line1": "65 Chulia Street", "city": "Singapore", "state": "", "postal_code": "049513", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "UOB Bank", "line1": "80 Raffles Place", "city": "Singapore", "state": "", "postal_code": "048624", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "Singapore Airlines", "line1": "Airline House, 25 Airline Road", "city": "Singapore", "state": "", "postal_code": "819829", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "Singtel", "line1": "31 Exeter Road", "city": "Singapore", "state": "", "postal_code": "239732", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "Lazada", "line1": "51 Bras Basah Road", "city": "Singapore", "state": "", "postal_code": "189554", "country": "SG", "source": "builtin_public", "type": "company"},
        {"name": "Razer", "line1": "1 one-north Crescent", "city": "Singapore", "state": "", "postal_code": "138538", "country": "SG", "source": "builtin_public", "type": "company"},
    ],
    "PH": [
        # 菲律宾 - 住宅地址 (15条)
        {"name": "Manila Residence 1", "line1": "123 Roxas Boulevard", "city": "Manila", "state": "", "postal_code": "1000", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Manila Residence 2", "line1": "456 Taft Avenue", "city": "Manila", "state": "", "postal_code": "1004", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Manila Residence 3", "line1": "789 Ermita Street", "city": "Manila", "state": "", "postal_code": "1000", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Makati Residence 1", "line1": "100 Ayala Avenue", "city": "Makati", "state": "", "postal_code": "1200", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Makati Residence 2", "line1": "200 Gil Puyat Avenue", "city": "Makati", "state": "", "postal_code": "1200", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Quezon City Residence 1", "line1": "50 Commonwealth Avenue", "city": "Quezon City", "state": "", "postal_code": "1100", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Quezon City Residence 2", "line1": "80 Katipunan Avenue", "city": "Quezon City", "state": "", "postal_code": "1108", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "BGC Residence 1", "line1": "30 26th Street", "city": "Taguig", "state": "", "postal_code": "1634", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "BGC Residence 2", "line1": "60 7th Avenue", "city": "Taguig", "state": "", "postal_code": "1634", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Pasig Residence 1", "line1": "40 Ortigas Avenue", "city": "Pasig", "state": "", "postal_code": "1600", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Cebu Residence 1", "line1": "25 Osmena Boulevard", "city": "Cebu City", "state": "", "postal_code": "6000", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Cebu Residence 2", "line1": "55 Colon Street", "city": "Cebu City", "state": "", "postal_code": "6000", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Davao Residence 1", "line1": "20 J.P. Laurel Avenue", "city": "Davao City", "state": "", "postal_code": "8000", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Alabang Residence 1", "line1": "15 Commerce Avenue", "city": "Muntinlupa", "state": "", "postal_code": "1780", "country": "PH", "source": "builtin_public", "type": "residential"},
        {"name": "Mandaluyong Residence 1", "line1": "10 Shaw Boulevard", "city": "Mandaluyong", "state": "", "postal_code": "1552", "country": "PH", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (8条)
        {"name": "UP Diliman Housing", "line1": "University of the Philippines", "city": "Quezon City", "state": "", "postal_code": "1101", "country": "PH", "source": "builtin_public", "type": "student"},
        {"name": "Ateneo Housing", "line1": "Katipunan Avenue", "city": "Quezon City", "state": "", "postal_code": "1108", "country": "PH", "source": "builtin_public", "type": "student"},
        {"name": "DLSU Housing", "line1": "2401 Taft Avenue", "city": "Manila", "state": "", "postal_code": "1004", "country": "PH", "source": "builtin_public", "type": "student"},
        {"name": "UST Housing", "line1": "España Boulevard", "city": "Manila", "state": "", "postal_code": "1008", "country": "PH", "source": "builtin_public", "type": "student"},
        {"name": "Mapua Housing", "line1": "Muralla Street", "city": "Manila", "state": "", "postal_code": "1002", "country": "PH", "source": "builtin_public", "type": "student"},
        {"name": "FEU Housing", "line1": "Nicanor Reyes Street", "city": "Manila", "state": "", "postal_code": "1008", "country": "PH", "source": "builtin_public", "type": "student"},
        {"name": "AdMU Housing", "line1": "Loyola Heights", "city": "Quezon City", "state": "", "postal_code": "1108", "country": "PH", "source": "builtin_public", "type": "student"},
        {"name": "USC Housing", "line1": "N. Escario Street", "city": "Cebu City", "state": "", "postal_code": "6000", "country": "PH", "source": "builtin_public", "type": "student"},
    ],
    "VN": [
        # 越南 - 住宅地址 (15条)
        {"name": "Ho Chi Minh Residence 1", "line1": "123 Nguyen Hue Boulevard", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Ho Chi Minh Residence 2", "line1": "456 Le Loi Street", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Ho Chi Minh Residence 3", "line1": "789 Dong Khoi Street", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Ho Chi Minh Residence 4", "line1": "321 Pasteur Street", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Ho Chi Minh Residence 5", "line1": "654 Pham Ngu Lao Street", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Hanoi Residence 1", "line1": "100 Hoan Kiem Street", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Hanoi Residence 2", "line1": "200 Ba Dinh Street", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Hanoi Residence 3", "line1": "50 Hang Bai Street", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Hanoi Residence 4", "line1": "80 Tran Hung Dao Street", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Da Nang Residence 1", "line1": "30 Bach Dang Street", "city": "Da Nang", "state": "", "postal_code": "550000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Da Nang Residence 2", "line1": "60 Tran Phu Street", "city": "Da Nang", "state": "", "postal_code": "550000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Nha Trang Residence 1", "line1": "40 Tran Phu Street", "city": "Nha Trang", "state": "", "postal_code": "650000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Hue Residence 1", "line1": "25 Le Loi Street", "city": "Hue", "state": "", "postal_code": "530000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Can Tho Residence 1", "line1": "15 Hai Ba Trung Street", "city": "Can Tho", "state": "", "postal_code": "900000", "country": "VN", "source": "builtin_public", "type": "residential"},
        {"name": "Vung Tau Residence 1", "line1": "10 Quang Trung Street", "city": "Vung Tau", "state": "", "postal_code": "790000", "country": "VN", "source": "builtin_public", "type": "residential"},
        # 学生宿舍 (8条)
        {"name": "VNU HCMC Housing", "line1": "Vietnam National University", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "student"},
        {"name": "HCMUT Housing", "line1": "268 Ly Thuong Kiet", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "student"},
        {"name": "VNU Hanoi Housing", "link1": "144 Xuan Thuy", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "student"},
        {"name": "HUST Housing", "line1": "1 Dai Co Viet", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "student"},
        {"name": "FPT University Housing", "line1": "Hoa Lac Hi-Tech Park", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "student"},
        {"name": "RMIT Vietnam Housing", "line1": "702 Nguyen Van Linh", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "student"},
        {"name": "DUT Housing", "line1": "54 Nguyen Luong Bang", "city": "Da Nang", "state": "", "postal_code": "550000", "country": "VN", "source": "builtin_public", "type": "student"},
        {"name": "CTU Housing", "line1": "Campus II", "city": "Can Tho", "state": "", "postal_code": "900000", "country": "VN", "source": "builtin_public", "type": "student"},
        # 学校/大学 (7条)
        {"name": "Vietnam National University HCMC", "line1": "Linh Trung Ward", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "school"},
        {"name": "Ho Chi Minh University of Technology", "line1": "268 Ly Thuong Kiet", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "school"},
        {"name": "Vietnam National University Hanoi", "line1": "144 Xuan Thuy", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "school"},
        {"name": "Hanoi University of Science and Technology", "line1": "1 Dai Co Viet", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "school"},
        {"name": "FPT University", "line1": "Hoa Lac Hi-Tech Park", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "school"},
        {"name": "Da Nang University of Technology", "line1": "54 Nguyen Luong Bang", "city": "Da Nang", "state": "", "postal_code": "550000", "country": "VN", "source": "builtin_public", "type": "school"},
        {"name": "Can Tho University", "line1": "Campus II", "city": "Can Tho", "state": "", "postal_code": "900000", "country": "VN", "source": "builtin_public", "type": "school"},
        # 办公室/企业 (10条)
        {"name": "VinGroup", "line1": "458 Minh Khai", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "Viettel", "line1": "57 Huynh Thuc Khang", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "FPT Corporation", "line1": "Keangnam Hanoi Landmark Tower", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "Vietcombank", "line1": "198 Tran Quang Khai", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "BIDV", "line1": "35 Hang Voi", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "Masan Group", "line1": "Masan Building", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "Vietnam Airlines", "line1": "200 Nguyen Son", "city": "Hanoi", "state": "", "postal_code": "100000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "Grab Vietnam", "line1": "The Vista Building", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "Shopee Vietnam", "line1": "Saigon Centre Tower 2", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "company"},
        {"name": "Lazada Vietnam", "line1": "194 Golden Building", "city": "Ho Chi Minh City", "state": "", "postal_code": "700000", "country": "VN", "source": "builtin_public", "type": "company"},
    ],
}


def _load_cache() -> dict[str, list[dict[str, str]]]:
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: dict[str, list[dict[str, str]]]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
    except Exception:
        pass


def _component(components: list[dict[str, Any]], kind: str, *, short: bool = False) -> str:
    for item in components or []:
        if kind in (item.get("types") or []):
            return str(item.get("shortText" if short else "longText") or item.get("longText") or "").strip()
    return ""


def _google_places(country: str, city: str, region: str) -> list[dict[str, str]]:
    key = str(os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    if not key:
        return []
    country_name = _COUNTRY_NAMES.get(country, country)
    query_city = city or region or country_name
    payload = {
        "textQuery": f"hotels and public businesses in {query_city}, {country_name}",
        "languageCode": "en",
        "maxResultCount": 20,
    }
    resp = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        json=payload,
        headers={
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.addressComponents",
            "Content-Type": "application/json",
        },
        timeout=20,
    )
    if resp.status_code != 200:
        return []
    out: list[dict[str, str]] = []
    for place in (resp.json() or {}).get("places") or []:
        components = place.get("addressComponents") or []
        item_country = _component(components, "country", short=True).upper()
        street_number = _component(components, "street_number")
        route = _component(components, "route")
        line1 = " ".join(part for part in (route, street_number) if part).strip()
        item_city = (
            _component(components, "locality")
            or _component(components, "postal_town")
            or _component(components, "administrative_area_level_2")
        )
        state = _component(components, "administrative_area_level_1", short=True)
        postal = _component(components, "postal_code")
        if item_country == country and line1 and item_city and postal:
            out.append({
                "name": str((place.get("displayName") or {}).get("text") or "").strip(),
                "line1": line1, "city": item_city, "state": state,
                "postal_code": postal, "country": country, "source": "google_places",
            })
    return out


def _nominatim(country: str, city: str, region: str) -> list[dict[str, str]]:
    global _LAST_NOMINATIM_AT
    country_name = _COUNTRY_NAMES.get(country, country)
    query_city = city or region or country_name
    queries = [
        f"hotel {query_city} {country_name}",
        f"restaurant {query_city} {country_name}",
        f"shopping centre {query_city} {country_name}",
    ]
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for query in queries:
        with _NOMINATIM_LOCK:
            delay = 1.05 - (time.monotonic() - _LAST_NOMINATIM_AT)
            if delay > 0:
                time.sleep(delay)
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": query, "format": "jsonv2", "addressdetails": 1,
                    "limit": 12, "countrycodes": country.lower(),
                },
                headers={"User-Agent": "pay153-public-address-resolver/1.0 (main.153.ink)"},
                timeout=20,
            )
            _LAST_NOMINATIM_AT = time.monotonic()
        if resp.status_code != 200:
            continue
        for row in resp.json() or []:
            address = row.get("address") or {}
            item_country = str(address.get("country_code") or "").upper()
            road = str(address.get("road") or address.get("pedestrian") or "").strip()
            house = str(address.get("house_number") or "").strip()
            place_name = str(
                address.get("tourism") or address.get("amenity") or address.get("shop")
                or row.get("name") or ""
            ).strip()
            line1 = " ".join(part for part in (road, house) if part).strip()
            if not house and place_name and road:
                line1 = f"{place_name}, {road}"
            item_city = str(
                address.get("city") or address.get("town") or address.get("village")
                or address.get("municipality") or address.get("county") or ""
            ).strip()
            state = str(address.get("state") or address.get("state_district") or "").strip()
            iso_state = str(address.get("ISO3166-2-lvl4") or address.get("ISO3166-2-lvl6") or "").upper()
            if country == "US" and iso_state.startswith("US-"):
                state = iso_state.split("-", 1)[1]
            postal = str(address.get("postcode") or "").strip()
            signature = (line1.lower(), item_city.lower(), postal.lower())
            if item_country == country and line1 and item_city and postal and signature not in seen:
                seen.add(signature)
                out.append({
                    "name": place_name, "line1": line1, "city": item_city,
                    "state": state, "postal_code": postal, "country": country,
                    "source": "openstreetmap_nominatim",
                })
        if len(out) >= 8:
            break
    return out


def _pick(key: str, rows: list[dict[str, str]], preferred_city: str = "") -> dict[str, str] | None:
    valid = [row for row in rows if row.get("line1") and row.get("city") and row.get("postal_code")]
    wanted = preferred_city.strip().casefold()
    if wanted:
        local = [row for row in valid if wanted in str(row.get("city") or "").casefold() or str(row.get("city") or "").casefold() in wanted]
        if local:
            valid = local
    if not valid:
        return None
    previous = _LAST_PICK.get(key, "")
    choices = [row for row in valid if f"{row.get('line1')}|{row.get('postal_code')}" != previous] or valid
    selected = dict(random.SystemRandom().choice(choices))
    _LAST_PICK[key] = f"{selected.get('line1')}|{selected.get('postal_code')}"
    return selected


def resolve_public_address(country: str, city: str = "", region: str = "", postal_hint: str = "") -> dict[str, str] | None:
    country = str(country or "").upper()
    city = str(city or "").strip()
    region = str(region or "").strip()
    cache_key = f"{country}|{city.lower()}|{region.lower()}"
    with _CACHE_LOCK:
        cache = _load_cache()
        cached = list(cache.get(cache_key) or [])
    # Refresh small pools; otherwise randomly reuse the validated cache.
    if len(cached) < 5:
        with _RESOLVE_LOCK:
            with _CACHE_LOCK:
                cache = _load_cache()
                cached = list(cache.get(cache_key) or [])
            if len(cached) < 5:
                fetched = _google_places(country, city, region)
                if not fetched:
                    try:
                        fetched = _nominatim(country, city, region)
                    except Exception:
                        fetched = []
                merged: list[dict[str, str]] = []
                signatures: set[tuple[str, str, str]] = set()
                for row in fetched + cached + list(_BUILTIN_PUBLIC_ADDRESSES.get(country) or []):
                    signature = (str(row.get("line1") or "").lower(), str(row.get("city") or "").lower(), str(row.get("postal_code") or "").lower())
                    if all(signature) and signature not in signatures:
                        signatures.add(signature)
                        merged.append(row)
                cached = merged[:40]
                with _CACHE_LOCK:
                    cache[cache_key] = cached
                    _save_cache(cache)
    if not cached:
        cached = list(_BUILTIN_PUBLIC_ADDRESSES.get(country) or [])
    return _pick(cache_key, cached, city)