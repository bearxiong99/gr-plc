/*
 * Gr-plc - IEEE 1901 module for GNU Radio
 * Copyright (C) 2016 Roee Bar <roeeb@ece.ubc.ca>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <gnuradio/io_signature.h>
#include <boost/thread.hpp>
#include "logging.h"
#include "phy_tx_impl.h"
#include <thread>

namespace gr {
  namespace plc {

    phy_tx::sptr
    phy_tx::make(int log_level)
    {
      return gnuradio::get_initial_sptr
        (new phy_tx_impl(log_level));
    }

    /*
     * The private constructor
     */
    phy_tx_impl::phy_tx_impl(int log_level)
      : gr::sync_block("phy_tx",
              gr::io_signature::make(0, 0, 0),
              gr::io_signature::make(1, 1, sizeof(gr_complex))),
            d_interframe_space(light_plc::phy_service::MIN_INTERFRAME_SPACE),
            d_log_level (log_level),
            d_init_done(false),
            d_datastream_offset(0),
            d_datastream_len(0),
            d_samples_since_last_tx(0),
            d_frame_ready(false),
            d_transmitter_state(HALT)
    {
      message_port_register_in(pmt::mp("mac in"));
      set_msg_handler(pmt::mp("mac in"), boost::bind(&phy_tx_impl::mac_in, this, _1));
      message_port_register_out(pmt::mp("mac out"));
    }

    /*
     * Our virtual destructor.
     */
    phy_tx_impl::~phy_tx_impl()
    {
    }

    void phy_tx_impl::mac_in (pmt::pmt_t msg) {
      if (!(pmt::is_pair(msg) && pmt::is_symbol(pmt::car(msg)) && pmt::is_dict(pmt::cdr(msg))))
          return;

      std::string cmd = pmt::symbol_to_string(pmt::car(msg));
      pmt::pmt_t dict = pmt::cdr(msg);

      if (cmd == "PHY-TXCONFIG") {
        if (d_transmitter_state == PREPARING) {
          PRINT_NOTICE("cannot config while preparing for tx");
          return;
        }
        // Set tone map
        if (pmt::dict_has_key(dict,pmt::mp("tone_map"))) {
          PRINT_DEBUG("setting custom tx tone map");
          pmt::pmt_t tone_map_pmt = pmt::dict_ref(dict, pmt::mp("tone_map"), pmt::PMT_NIL);
          size_t tone_map_len = 0;
          const uint8_t *tone_map_blob = pmt::u8vector_elements(tone_map_pmt, tone_map_len);
          light_plc::tone_map_t tone_map;
          for (size_t j = 0; j<tone_map_len; j++)
            tone_map[j] = (light_plc::modulation_type_t)tone_map_blob[j];
          d_phy_service.set_tone_map(tone_map);
        }
      }

      else if (cmd == "PHY-TXINIT") {
        if (!d_init_done) {
          if (pmt::dict_has_key(dict,pmt::mp("id"))) {
            std::string role = pmt::symbol_to_string(pmt::dict_ref(dict, pmt::mp("id"), pmt::PMT_NIL));
            set_block_alias(alias() + " (" + role + ")");
          }
          INIT_GR_LOG

          light_plc::tone_mask_t tone_mask;
          light_plc::sync_tone_mask_t sync_tone_mask;
          if (pmt::dict_has_key(dict,pmt::mp("broadcast_tone_mask")) &&
              pmt::dict_has_key(dict,pmt::mp("sync_tone_mask")))
          {
            PRINT_DEBUG("initializing transmitter");

            // Set broadcast tone mask
            pmt::pmt_t tone_mask_pmt = pmt::dict_ref(dict, pmt::mp("broadcast_tone_mask"), pmt::PMT_NIL);
            size_t tone_mask_len = 0;
            const uint8_t *tone_mask_blob = pmt::u8vector_elements(tone_mask_pmt, tone_mask_len);
            assert(tone_mask_len == tone_mask.size());
            for (size_t j = 0; j<tone_mask_len; j++)
              tone_mask[j] = tone_mask_blob[j];

            // Set sync tone mask
            pmt::pmt_t sync_tone_mask_pmt = pmt::dict_ref(dict, pmt::mp("sync_tone_mask"), pmt::PMT_NIL);
            size_t sync_tone_mask_len = 0;
            const uint8_t *sync_tone_mask_blob = pmt::u8vector_elements(sync_tone_mask_pmt, sync_tone_mask_len);
            assert(sync_tone_mask_len == sync_tone_mask.size());
            for (size_t j = 0; j<sync_tone_mask_len; j++)
              sync_tone_mask[j] = sync_tone_mask_blob[j];

            // Set channel estimation mode
            pmt::pmt_t channel_est_mode_pmt = pmt::dict_ref(dict, pmt::mp("channel_est_mode"), pmt::PMT_NIL);
            light_plc::channel_est_t channel_est_mode = (light_plc::channel_est_t)pmt::to_uint64(channel_est_mode_pmt);

            // Set inter-frame space
            pmt::pmt_t interframe_space_pmt = pmt::dict_ref(dict, pmt::mp("interframe_space"), pmt::PMT_NIL);
            d_interframe_space = pmt::to_uint64(interframe_space_pmt);

            d_phy_service = light_plc::phy_service(tone_mask, tone_mask, sync_tone_mask, channel_est_mode, d_log_level >= 3);
          }

          d_transmitter_state = READY;
          d_init_done = true;
          PRINT_DEBUG("init done");
        } else
          PRINT_NOTICE("cannot init more than once");
      }

      else if (cmd == "PHY-TXSTART") {
        if (d_transmitter_state == READY) {
          // Get frame control
          pmt::pmt_t mpdu_fc_pmt = pmt::dict_ref(dict, pmt::mp("frame_control"), pmt::PMT_NIL);
          size_t mpdu_fc_length = 0;
          const unsigned char *mpdu_fc = pmt::u8vector_elements(mpdu_fc_pmt, mpdu_fc_length);
          d_mpdu_fc = std::vector<unsigned char>(mpdu_fc, mpdu_fc + mpdu_fc_length);
          // Get payload
          size_t mpdu_payload_length = 0;
          const unsigned char *mpdu_payload = NULL;
          d_mpdu_payload = std::vector<unsigned char>(0);
          if (pmt::dict_has_key(dict,pmt::mp("payload"))) {
            pmt::pmt_t mpdu_payload_pmt = pmt::dict_ref(dict, pmt::mp("payload"), pmt::PMT_NIL);
            mpdu_payload = pmt::u8vector_elements(mpdu_payload_pmt, mpdu_payload_length);
            d_mpdu_payload = std::vector<unsigned char>(mpdu_payload, mpdu_payload + mpdu_payload_length);
          }
          PRINT_DEBUG("received new MPDU from MAC");
          d_transmitter_state = PREPARING;
          std::thread{&phy_tx_impl::create_ppdu, this}.detach(); // creating the PPDU in a new thread not to starve the work routine
        } else {
          PRINT_NOTICE("received MPDU while transmitter is not ready, dropping MPDU");
        }
      }
    }

    void phy_tx_impl::create_ppdu() {
      d_datastream = d_phy_service.create_ppdu(d_mpdu_fc.data(), d_mpdu_fc.size(), d_mpdu_payload.data(), d_mpdu_payload.size());
      d_datastream_len = d_datastream.size();
      d_frame_ready = true;
      return;
    }

    int
    phy_tx_impl::work(int noutput_items,
              gr_vector_const_void_star &input_items,
              gr_vector_void_star &output_items)
    {
      int i = 0;
      gr_complex *out = (gr_complex *) output_items[0];

        switch (d_transmitter_state) {
          case TX: {
            i = std::min(noutput_items, d_datastream_len - d_datastream_offset);
            if (d_datastream_offset == 0 && i > 0) {
              // add tags
              pmt::pmt_t key = pmt::string_to_symbol("packet_len");
              pmt::pmt_t value = pmt::from_long(d_datastream_len);
              pmt::pmt_t srcid = pmt::string_to_symbol(alias());
              add_item_tag(0, nitems_written(0), key, value, srcid);
            }

            std::memcpy(out, &d_datastream[d_datastream_offset], sizeof(light_plc::vector_complex::value_type)*i);
            d_datastream_offset += i;
            PRINT_DEBUG("state = TX, copied " + std::to_string(d_datastream_offset) + "/" + std::to_string(d_datastream_len));

            if(i > 0 && d_datastream_offset == d_datastream_len) {
              PRINT_DEBUG("state = TX, MPDU sent!");
              d_datastream_offset = 0;
              d_datastream_len = 0;
              d_samples_since_last_tx = 0;
              d_transmitter_state = READY;
              d_frame_ready = false;
              pmt::pmt_t dict = pmt::make_dict();
              message_port_pub(pmt::mp("mac out"), pmt::cons(pmt::mp("PHY-TXEND"), dict));
            }
            break;
          }

          case PREPARING:
            if (d_frame_ready) {
              if (d_samples_since_last_tx >= d_interframe_space)
                d_transmitter_state = TX;
              else {
                i = std::min(d_interframe_space - d_samples_since_last_tx, noutput_items);
                d_samples_since_last_tx += i;
                std::memset(out, 0, sizeof(gr_complex)*i);
              }
              break;
            }

          case READY: {
            i = noutput_items;
            std::memset(out, 0, sizeof(gr_complex)*i);
            pmt::pmt_t key = pmt::string_to_symbol("packet_len");
            pmt::pmt_t value = pmt::from_long(i);
            pmt::pmt_t srcid = pmt::string_to_symbol(alias());
            add_item_tag(0, nitems_written(0), key, value, srcid);
            d_samples_since_last_tx += i;
            break;
          }

          case HALT:
            break;
        }
      // Tell runtime system how many output items we produced.
      return i;
    }
  } /* namespace plc */
} /* namespace gr */
