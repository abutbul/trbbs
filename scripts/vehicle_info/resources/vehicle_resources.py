"""
Definitions for vehicle data resources.
"""

# Define the resources and their corresponding CSV files with specific encodings
VEHICLE_RESOURCES = [
    {
        'id': '053cea08-09bc-40ec-8f7a-156f0677aff3',
        'name': 'Vehicle Details',
        'csv': '053cea08-09bc-40ec-8f7a-156f0677aff3.csv',
        'encoding': 'cp1255'
    },
    {
        'id': '0866573c-40cd-4ca8-91d2-9dd2d7a492e5',
        'name': 'Vehicle Grira',
        'csv': '0866573c-40cd-4ca8-91d2-9dd2d7a492e5.csv',
        'encoding': 'utf-8'
    },
    {
        'id': 'c8b9f9c8-4612-4068-934f-d4acd2e3c06e',
        'name': 'Vehicle Handicap',
        'csv': 'c8b9f9c8-4612-4068-934f-d4acd2e3c06e.csv',
        'encoding': 'utf-8'
    },
    {
        'id': 'cf29862d-ca25-4691-84f6-1be60dcb4a1e',
        'name': 'Vehicle Tziburi',
        'csv': 'cf29862d-ca25-4691-84f6-1be60dcb4a1e.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '0866573c-40cd-4ca8-91d2-9dd2d7a492e5',
        'name': 'Vehicle Tziburi Grira',
        'csv': '0866573c-40cd-4ca8-91d2-9dd2d7a492e5.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '7cb2bd95-bf2e-49b6-aea1-fcb5ff6f0473',
        'name': 'Vehicle Plitat Zihum',
        'csv': '7cb2bd95-bf2e-49b6-aea1-fcb5ff6f0473.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '36bf1404-0be4-49d2-82dc-2f1ead4a8b93',
        'name': 'Vehicle Recall',
        'csv': '36bf1404-0be4-49d2-82dc-2f1ead4a8b93.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '58dc4654-16b1-42ed-8170-98fadec153ea',
        'name': 'Vehicle Tzama',
        'csv': '58dc4654-16b1-42ed-8170-98fadec153ea.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '851ecab1-0622-4dbe-a6c7-f950cf82abf9',
        'name': 'Vehicle Mevutalim',
        'csv': '851ecab1-0622-4dbe-a6c7-f950cf82abf9.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '4e6b9724-4c1e-43f0-909a-154d4cc4e046',
        'name': 'Vehicle Mevutalim 2010-2016',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': 'ec8cbc34-72e1-4b69-9c48-22821ba0bd6c',
        'name': 'Vehicle Mevutalim 2000-2009',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': 'f6efe89a-fb3d-43a4-bb61-9bf12a9b9099',
        'name': 'Vehicle Lo Peilim - Degem',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '6f6acd03-f351-4a8f-8ecf-df792f4f573a',
        'name': 'Vehicle Lo Peilim - No Degem',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': 'bf9df4e2-d90d-4c0a-a400-19e15af8e95f',
        'name': 'Du Galgali',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': 'cd3acc5c-03c3-4c89-9c54-d40f93c0d790',
        'name': '3.5 Ton Vehicles',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '03adc637-b6fe-402b-9937-7c3d3afc9140',
        'name': 'Self Imports',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '56063a99-8a3e-4ff4-912e-5966c0279bad',
        'name': 'Car History 1',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': 'bb2355dc-9ec7-4f06-9c3f-3344672171da',
        'name': 'Car History 2',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '10283c63-5bab-4c24-b326-1680afd579ad',
        'name': 'Bad Diesel 1',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '48986b43-997c-43bc-b03a-ac305a1b41eb',
        'name': 'Bad Diesel 2',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '14c0c07b-69e9-4eaf-affc-ff01b2d0def4',
        'name': 'Particle Filter 1',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    },
    {
        'id': '610887e5-6887-4f94-b5d6-e09a76285b28',
        'name': 'Particle Filter 2',
        'csv': '4e6b9724-4c1e-43f0-909a-154d4cc4e046.csv',
        'encoding': 'utf-8'
    }
]

# Mapping of property names to Hebrew labels
PROPERTY_MAPPING = {
    'mispar_rechev': 'מספר רכב',
    'tozeret_nm': 'יצרן',
    'sug_degem': 'סוג דגם',
    'kinuy_mishari': 'כינוי מסחרי',
    'baalut': 'בעלות',
    'tzeva_rechev': 'צבע רכב',
    'nefach_manoa': 'נפח מנוע',
    'misgeret': 'שילדה',
    'merkav': 'מרכב',
    'hanaa': 'הנעה',
    'sug_delek_nm': 'סוג דלק',
    'ramat_gimur': 'רמת גימור',
    'moed_aliya_lakvish': 'עלייה לכביש',
    'shnat_yitzur': 'שנת ייצור',
    'mivchan_acharon_dt': 'טסט אחרון',
    'tokef_dt': 'תוקף רישיון',
    'sach_agara': 'סכום אגרה',
    'horaat_rishum': 'הוראת רישום',
    'degem_cd': 'מזהה דגם',
    'degem_manoa': 'דגם מנוע',
    'koah_sus': 'כוח סוס',
    'mishkal_kolel': 'משקל כולל',
    'mispar_moshavim': 'מספר מושבים',
    'mispar_dlatot': 'מספר דלתות',
    'halonot_hashmaliim': 'חלונות חשמליים',
    'zmig_kidmi': 'צמיג קדמי',
    'zmig_ahori': 'צמיג אחורי',
    'kosher_grira_im_blamim': 'כושר גרירה עם בלמים',
    'kosher_grira_bli_blamim': 'כושר גרירה בלי בלמים',
    'teknologiat_hanaa': 'טכנולוגיית הנעה',
    'sug_mamir': 'סוג ממיר',
    'sug_tkina': 'סוג תקינה',
    'kamat_kariot_avir': 'כמות כריות אוויר',
    'nikud_betihut': 'ניקוד בטיחות',
    'degem_nm': 'דגם',
    'grira_nm': 'גררה',
    'kod_mehirut_tzmig_ahori': 'קוד מהירות צמיג אחורי',
    'kod_mehirut_tzmig_kidmi': 'קוד מהירות צמיג קדמי',
    'kod_omes_tzmig_ahori': 'קוד עומס צמיג אחורי',
    'kod_omes_tzmig_kidmi': 'קוד עומס צמיג קדמי',
    'kvutzat_zihum': 'קבוצת זיהום',
    'ramat_eivzur_betihuty': 'רמת איבזור בטיחותי',
    'tozeret_cd': 'קוד תוצרת',
    'tzeva_cd': 'קוד צבע',
    'SUG TAV': 'סוג תו נכה',
    'TAARICH HAFAKAT TAV': 'תאריך הפקת תו',
    'mispar_mekomot': 'מספר מקומות',
    'mispar_mekomot_leyd_nahag': 'מספר מקומות ליד נהג',
    'sug_rechev_nm': 'סוג רכב ציבורי',
    'sug_rechev_EU_cd': 'קוד רכב EU',
    'sug_rechev_EU_nm': 'סוג רכב EU',
    'sug_rechev_cd': 'קוד סוג רכב',
    'bitul_nm': 'ביטול',
    'taarich_hatkana': 'תאריך התקנה מסננים לצמצום פליטת מזהמים',
    'rishum_rishon_dt': 'רישום ראשון',
    'recall_id': 'מזהה קריאת תיקון',
    'sug_recall': 'סוג קריאת תיקון',
    'teur_takala': 'תיאור תקלה',
    'bitul_dt': ' תאריך ביטול רשיון(!!!)',
    'sug_yevu': 'סוג יבוא',
    'baalut_dt': 'תאריך העברת בעלות',
    'gapam_ind': 'גפ"ם',
    'kilometer_test_aharon': 'קילומטראז אחרון',
    'mispar_manoa': 'מספר מנוע',
    'shinui_mivne_ind': 'שינוי מבנה',
    'shinui_zmig_ind': 'שינוי צמיג',
    'shnui_zeva_ind': 'שינוי צבע'
}