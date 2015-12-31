/* -*- c++ -*- */

#ifndef INCLUDED_PLC_PHY_RX_IMPL_H
#define INCLUDED_PLC_PHY_RX_IMPL_H

#include <plc/phy_rx.h>
#include <lightplc/phy_service.h>
#include <list>
#include <string>

namespace gr {
  namespace plc {

    class phy_rx_impl : public phy_rx
    {
     private:
      static const int SYNCP_SIZE;
      static const int SYNC_LENGTH;
      static const int FINE_SYNC_LENGTH;
      static const int PREAMBLE_SIZE;
      static const int FRAME_CONTROL_SIZE;
      static const float THRESHOLD;
      static const float MIN_ENERGY;
      static const int MIN_PLATEAU;
      static const int MIN_INTERFRAME_SPACE;

      light_plc::phy_service d_phy_service;
      const bool d_debug;
      const bool d_info;
      bool d_init_done;
      enum {SEARCH, SYNC, COPY_PREAMBLE, COPY_FRAME_CONTROL, COPY_PAYLOAD, RESET, IDLE, HALT} d_receiver_state;
      float d_search_corr;
      float d_energy;
      int d_plateau;
      int d_payload_size;
      int d_payload_offset;
      light_plc::vector_float d_preamble;
      light_plc::vector_float d_frame_control;
      light_plc::vector_float d_payload;
      pmt::pmt_t d_frame_control_pmt;
      float d_sync_min;
      int d_sync_min_index;
      int d_frame_control_offset;
      int d_preamble_offset;
      float *d_preamble_corr;
      int d_frame_start;
      light_plc::vector_int d_output_datastream;
      int d_output_datastream_offset;
      int d_output_datastream_len;
      std::vector<float> d_noise;
      int d_noise_offset;
      int d_inter_frame_space_offset;
      std::string d_name;

     public:
      phy_rx_impl(bool info, bool debug);
      ~phy_rx_impl();
      void mac_in (pmt::pmt_t msg);
      void forecast (int noutput_items, gr_vector_int &ninput_items_required);

      // Where all the action really happens
      int work(int noutput_items,
	       gr_vector_const_void_star &input_items,
	       gr_vector_void_star &output_items);
    };

  } // namespace plc
} // namespace gr

#endif /* INCLUDED_PLC_PHY_RX_IMPL_H */

