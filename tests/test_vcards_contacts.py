# from contacts_names_from_vcards import readVCardsFile

import os
from Whatsapp_Chat_Exporter.vcards_contacts import (
    map_number_to_name,
    normalize_number,
    process_vcard_entry,
    read_vcards_file,
)


def test_readVCardsFile():
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    data = read_vcards_file(os.path.join(data_dir, "contacts.vcf"), "852")
    if data:  
        print("Found Names")
        print("-----------------------")
        for count, contact_tuple in enumerate(data, start=1):
            # The name is the second element of the tuple (at index 1)
            name = contact_tuple[1]
            
            # Print the count and the name
            print(f"{count}. {name}")
        print(data)
    assert len(data) == 6
    # Test simple contact name
    assert data[0][1] == "Sample Contact"
    # Test complex name
    assert data[1][1] == "Yard Lawn Guy, Jose Lopez"
    # Test name with emoji
    assert data[2][1] == "John Butler 🌟💫🌟"
    # Test note with multi-line encoding
    assert data[3][1] == "Airline Contact #'s"
    # Test address with multi-line encoding
    assert data[4][1] == "James Peacock Elementary"
    # Test business entry using ORG but not F/FN
    assert data[5][1] == "AAA Car Service"


def test_create_number_to_name_dicts():
    pass


def test_fuzzy_match_numbers():
    pass


def test_normalize_number():
    assert normalize_number('0531234567', '1') == '1531234567'
    assert normalize_number('001531234567', '2') == '1531234567'
    assert normalize_number('+1531234567', '34') == '1531234567'
    assert normalize_number('053(123)4567', '34') == '34531234567'
    assert normalize_number('0531-234-567', '58') == '58531234567'


# read_vcards_file splits on "BEGIN:VCARD", so entries reach
# process_vcard_entry WITHOUT the BEGIN line.
def _vcard_entry(tel_line):
    return f"VERSION:3.0\nN:Test;Contact;;;\nFN:Test Contact\n{tel_line}\nEND:VCARD"


def test_waid_preferred_over_tel_value():
    # Mexican mobile numbers: the TEL value (E.164, no carrier 1) does not
    # match the JID (52 1 XXX...), but the waid parameter is the exact ID.
    contact = process_vcard_entry(_vcard_entry(
        "TEL;type=Celular;waid=5213314010847:+52 33 1401 0847"))
    mapping = map_number_to_name([contact], "52")
    assert mapping == [("5213314010847", "Test Contact")]


def test_tel_value_used_when_no_waid():
    contact = process_vcard_entry(_vcard_entry(
        "TEL;type=Celular:+52 33 1401 0847"))
    mapping = map_number_to_name([contact], "52")
    assert mapping == [("523314010847", "Test Contact")]


def test_waid_only_digits_kept():
    contact = process_vcard_entry(_vcard_entry(
        "TEL;type=Celular;waid=\"+52 133 1401 0847\":+52 33 1401 0847"))
    mapping = map_number_to_name([contact], "52")
    assert mapping == [("5213314010847", "Test Contact")]
