"""Hindi text for the care content, keyed by the English sentence (careplan._t looks it up).

Needs a native Hindi speaker's check before use with real patients, like the Kannada text.
A missing entry simply falls back to English on screen and is not spoken in Hindi.
"""

HI = {
    # headlines
    "First: see the specialist. Then: what your habits mean for your mouth.":
        "पहले विशेषज्ञ से मिलें। फिर जानें: आपकी आदतें आपके मुँह पर क्या असर डालती हैं।",
    "A doctor is checking your photos. Meanwhile, what your habits mean for your mouth.":
        "डॉक्टर आपकी तस्वीरें देख रहे हैं। तब तक जानें: आपकी आदतें आपके मुँह पर क्या असर डालती हैं।",
    "The photos need to be taken again. Meanwhile, what your habits mean for your mouth.":
        "तस्वीरें दोबारा लेनी होंगी। तब तक जानें: आपकी आदतें आपके मुँह पर क्या असर डालती हैं।",
    "One sign to watch. What happens if your habits continue - and if you stop.":
        "एक लक्षण पर ध्यान रखना है। आदत जारी रही तो क्या होगा - और छोड़ दी तो क्या होगा।",
    "Your mouth looks healthy today. Your habits can change that over the years.":
        "आज आपका मुँह स्वस्थ दिखता है। पर आपकी आदतें सालों में इसे बदल सकती हैं।",
    "Your mouth looks healthy today - keep it that way.":
        "आज आपका मुँह स्वस्थ दिखता है - इसे ऐसे ही बनाए रखें।",
    # habit facts
    "Gutka, khaini and tobacco in paan are proven to cause mouth cancer.":
        "गुटखा, खैनी और पान में तंबाकू से मुँह का कैंसर होता है - यह साबित हो चुका है।",
    "Where the quid rests, the cheek lining is damaged again and again - white patches often start there.":
        "जहाँ तंबाकू रखा जाता है, वहाँ गाल की अंदरूनी परत बार-बार खराब होती है - सफ़ेद धब्बे अक्सर वहीं से शुरू होते हैं।",
    "Beedi and cigarette smoke damages the lining of the mouth and throat.":
        "बीड़ी और सिगरेट का धुआँ मुँह और गले की अंदरूनी परत को नुकसान पहुँचाता है।",
    "Areca nut on its own - even without tobacco - is proven to cause mouth cancer.":
        "सुपारी अकेले भी - बिना तंबाकू के - मुँह का कैंसर करती है, यह साबित हो चुका है।",
    "Areca slowly stiffens the inside of the mouth (submucous fibrosis): burning first, then the mouth opens less and less.":
        "सुपारी धीरे-धीरे मुँह के अंदर को सख़्त कर देती है: पहले जलन, फिर मुँह कम-कम खुलने लगता है।",
    "Drinking alcohol as well as using tobacco raises the risk more than either alone.":
        "तंबाकू के साथ शराब पीने से ख़तरा और भी ज़्यादा बढ़ जाता है।",
    # stages
    "If areca chewing continues": "अगर सुपारी खाना जारी रहा",
    "If tobacco use continues": "अगर तंबाकू जारी रहा",
    "Burning with spicy food, blanching of the cheeks": "तीखा खाने पर जलन, गालों का अंदर से सफ़ेद पड़ना",
    "Stiff bands inside the cheeks; the mouth opens less": "गालों के अंदर सख़्त पट्टियाँ; मुँह कम खुलता है",
    "Risk of mouth cancer rises, especially with tobacco": "मुँह के कैंसर का ख़तरा बढ़ता है, ख़ासकर तंबाकू के साथ",
    "Stained teeth, gum and cheek irritation": "दाँतों पर दाग़, मसूड़ों और गालों में जलन",
    "White or red patches where tobacco touches the mouth": "जहाँ तंबाकू छूता है वहाँ सफ़ेद या लाल धब्बे",
    "Some patches turn into mouth cancer": "कुछ धब्बे मुँह के कैंसर में बदल जाते हैं",
    # if you quit
    "Within 5 years of stopping smoking, the risk of mouth cancer is cut in half.":
        "धूम्रपान छोड़ने के 5 साल के अंदर मुँह के कैंसर का ख़तरा आधा हो जाता है।",
    "Stopping now lowers the risk year after year, and early patches can heal once the habit stops.":
        "अभी छोड़ने से ख़तरा साल-दर-साल घटता है, और आदत छूटने पर शुरुआती धब्बे ठीक हो सकते हैं।",
    "Whatever you decide: see a doctor early for any patch, sore or stiffness - early is easier to treat.":
        "आप जो भी तय करें: किसी भी धब्बे, छाले या सख़्ती के लिए जल्दी डॉक्टर को दिखाएँ - जल्दी इलाज आसान होता है।",
    "These are facts about many people with these habits, not a prediction about you.":
        "ये इन आदतों वाले बहुत से लोगों के बारे में तथ्य हैं, आपके बारे में भविष्यवाणी नहीं।",
    # roadmap steps
    "See the specialist": "विशेषज्ञ से मिलें",
    "A specialist must examine the finding - early is much easier to treat.":
        "विशेषज्ञ को इसकी जाँच करनी चाहिए - जल्दी इलाज बहुत आसान होता है।",
    "Go to {facility} by {due}. Take the referral slip and your health card.":
        "{due} तक {facility} जाएँ। रेफ़रल पर्ची और अपना हेल्थ कार्ड साथ ले जाएँ।",
    "Wait for the doctor's photo review": "डॉक्टर की फ़ोटो जाँच का इंतज़ार करें",
    "A doctor looks at your photos before any trip is needed.": "कहीं जाने से पहले डॉक्टर आपकी तस्वीरें देखते हैं।",
    "Your ASHA will tell you the result within a week.": "एक हफ़्ते के अंदर आपकी आशा दीदी नतीजा बताएँगी।",
    "Retake the photos": "तस्वीरें दोबारा लें",
    "Some photos were not clear enough to judge.": "कुछ तस्वीरें साफ़ नहीं थीं।",
    "Your ASHA will visit again to take them.": "आपकी आशा दीदी दोबारा आकर तस्वीरें लेंगी।",
    "Recheck the patch in 2 weeks": "2 हफ़्ते में धब्बे की फिर जाँच करें",
    "A patch that is still there after 2 weeks must be seen by a specialist.":
        "जो धब्बा 2 हफ़्ते बाद भी रहे, उसे विशेषज्ञ को दिखाना ज़रूरी है।",
    "If it has not gone, your ASHA arranges the referral.": "अगर वह नहीं गया, तो आपकी आशा दीदी रेफ़रल करवाएँगी।",
    "Choose your quit date": "छोड़ने का दिन चुनें",
    "A fixed date makes quitting real - most people who succeed pick a day.":
        "तय दिन होने से छोड़ना आसान होता है - जो लोग सफल होते हैं, वे ज़्यादातर एक दिन चुनते हैं।",
    "Pick a day within 2 weeks and tell your family.": "2 हफ़्ते के अंदर का एक दिन चुनें और परिवार को बताएँ।",
    "Call the free quitline": "मुफ़्त क्विटलाइन पर कॉल करें",
    "Trained counsellors help you plan and stay quit, in your language.":
        "प्रशिक्षित सलाहकार आपकी भाषा में छोड़ने और छोड़े रहने में मदद करते हैं।",
    "National Tobacco Quitline: 1800-11-2356 (free).": "राष्ट्रीय तंबाकू क्विटलाइन: 1800-11-2356 (मुफ़्त)।",
    "Swap the after-meal chew": "खाने के बाद की आदत बदलें",
    "Cravings come at the same times every day - after meals, with tea, with friends.":
        "तलब रोज़ एक ही समय पर आती है - खाने के बाद, चाय के साथ, दोस्तों के साथ।",
    "Keep saunf (fennel), cardamom or sugar-free gum ready; drink water; walk for 5 minutes.":
        "सौंफ़, इलायची या शुगर-फ़्री गम पास रखें; पानी पिएँ; 5 मिनट टहलें।",
    "Make home smoke-free": "घर को धुआँ-मुक्त बनाएँ",
    "Fewer cues at home means fewer cravings - and protects your family.":
        "घर में कम याद दिलाने वाली चीज़ें, यानी कम तलब - और परिवार भी सुरक्षित।",
    "Remove beedis, lighters and ashtrays; never smoke indoors.":
        "बीड़ी, लाइटर और ऐशट्रे हटा दें; घर के अंदर कभी धूम्रपान न करें।",
    "Ask about nicotine replacement": "निकोटीन रिप्लेसमेंट के बारे में पूछें",
    "Heavy daily use is hard to stop alone; nicotine gum or patches ease withdrawal.":
        "रोज़ ज़्यादा सेवन अकेले छोड़ना मुश्किल है; निकोटीन गम या पैच मदद करते हैं।",
    "Ask the doctor or pharmacist which is right for you.": "डॉक्टर या फ़ार्मासिस्ट से पूछें कि आपके लिए क्या सही है।",
    "Daily mouth-opening exercise": "रोज़ मुँह खोलने का व्यायाम",
    "Gentle stretching helps keep the mouth from getting stiffer.": "हल्का व्यायाम मुँह को और सख़्त होने से बचाता है।",
    "Open wide slowly 10 times, twice a day - stop if it hurts and tell the doctor.":
        "दिन में दो बार, 10 बार धीरे-धीरे मुँह पूरा खोलें - दर्द हो तो रुकें और डॉक्टर को बताएँ।",
    "Go easy on very spicy food": "बहुत तीखा खाना कम करें",
    "Burning with spicy food is a sign the lining is irritated.": "तीखा खाने पर जलन का मतलब है कि अंदर की परत में जलन है।",
    "Choose milder food until the doctor has seen you.": "डॉक्टर को दिखाने तक हल्का खाना खाएँ।",
    "Check your mouth every Sunday": "हर रविवार अपना मुँह जाँचें",
    "You will notice changes early - most warning signs do not hurt.":
        "बदलाव जल्दी दिखेंगे - ज़्यादातर चेतावनी के लक्षणों में दर्द नहीं होता।",
    "Use a mirror and good light: look for white or red patches, sores that do not heal, stiffness.":
        "आईना और अच्छी रोशनी लें: सफ़ेद या लाल धब्बे, न भरने वाले छाले और सख़्ती देखें।",
    "Brush twice, rinse after meals": "दो बार ब्रश करें, खाने के बाद कुल्ला करें",
    "A clean mouth heals better and makes changes easier to see.": "साफ़ मुँह जल्दी ठीक होता है और बदलाव आसानी से दिखते हैं।",
    "Soft brush, fluoride paste; rinse with water after eating.": "नरम ब्रश, फ़्लोराइड पेस्ट; खाने के बाद पानी से कुल्ला करें।",
    "Eat fruit and vegetables every day": "रोज़ फल और सब्ज़ियाँ खाएँ",
    "Good for the mouth and overall health; some studies link fruit and vegetables to a lower risk of mouth cancer. It supports - but never replaces - quitting and seeing the doctor.":
        "मुँह और पूरी सेहत के लिए अच्छा; कुछ अध्ययन फल-सब्ज़ियों को मुँह के कैंसर के कम ख़तरे से जोड़ते हैं। यह मदद करता है - पर आदत छोड़ने और डॉक्टर को दिखाने की जगह कभी नहीं ले सकता।",
    "Aim for local seasonal fruit, greens, guava, amla, carrots; drink enough water.":
        "स्थानीय मौसमी फल, हरी सब्ज़ियाँ, अमरूद, आँवला, गाजर खाएँ; पर्याप्त पानी पिएँ।",
    "Cut down alcohol": "शराब कम करें",
    "Alcohol with tobacco multiplies the damage.": "तंबाकू के साथ शराब नुकसान को कई गुना कर देती है।",
    "Set alcohol-free days each week; avoid drinking while chewing or smoking.":
        "हर हफ़्ते कुछ दिन बिना शराब के रखें; तंबाकू चबाते या पीते समय शराब न पिएँ।",
    "Next screening with your ASHA": "आशा दीदी के साथ अगली जाँच",
    "Regular checks catch changes before they become serious.": "नियमित जाँच से बदलाव गंभीर होने से पहले पकड़ में आते हैं।",
    "Your ASHA will visit around {rescreen}.": "आपकी आशा दीदी लगभग {rescreen} में आएँगी।",
    # phases
    "Medical": "इलाज", "Quitting": "छोड़ना", "Mouth care": "मुँह की देखभाल", "Food": "खान-पान", "Follow-up": "अगली जाँच",
}

# what the voice says for steps whose text holds personal details (hospital name, dates): those are never spoken or
# sent anywhere - the voice points to the screen instead
SPEAK_HOW = {
    "see_specialist": {
        "en": "Go to the hospital shown on the screen, before the date shown. Take the referral slip and your health card.",
        "kn": "ಪರದೆಯಲ್ಲಿ ತೋರಿಸಿರುವ ದಿನಾಂಕದ ಒಳಗೆ, ತೋರಿಸಿರುವ ಆಸ್ಪತ್ರೆಗೆ ಹೋಗಿ. ರೆಫರಲ್ ಚೀಟಿ ಮತ್ತು ಆರೋಗ್ಯ ಕಾರ್ಡ್ ತೆಗೆದುಕೊಳ್ಳಿ.",
        "hi": "स्क्रीन पर दिखाई गई तारीख़ से पहले, दिखाए गए अस्पताल जाएँ। रेफ़रल पर्ची और अपना हेल्थ कार्ड साथ ले जाएँ।",
    },
    "rescreen": {
        "en": "Your ASHA will visit you again in the month shown on the screen.",
        "kn": "ಪರದೆಯಲ್ಲಿ ತೋರಿಸಿರುವ ತಿಂಗಳಲ್ಲಿ ನಿಮ್ಮ ಆಶಾ ಮತ್ತೆ ಭೇಟಿ ನೀಡುತ್ತಾರೆ.",
        "hi": "स्क्रीन पर दिखाए गए महीने में आपकी आशा दीदी फिर आएँगी।",
    },
}
