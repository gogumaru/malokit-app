//
//  Item.swift
//  Malokit
//
//  Created by Benedikta Anin on 10/08/26.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
